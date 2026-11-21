"""update_contact writes back what was read (#119: B5)."""
import asyncio
from unittest.mock import MagicMock

import pytest

from meshcore.commands import CommandHandler
from meshcore.events import Event, EventType, Subscription
from meshcore.reader import MessageReader

pytestmark = pytest.mark.asyncio

KEY = bytes(range(32))
# CMD_ADD_UPDATE_CONTACT: code, key, type, flags, path length, path (64), name (32), last advert, lat, lon
NAME_AT = 1 + 32 + 3 + 64
LAT_AT = NAME_AT + 32 + 4


class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []

    async def dispatch(self, event):
        self.dispatched_events.append(event)


def contact_frame(name: bytes, lat: int, lon: int) -> bytes:
    """A CONTACT frame as the device sends it."""
    return (
        b"\x03" + KEY + b"\x02\x00\xff" + bytes(64) + name.ljust(32, b"\0")
        + (1000).to_bytes(4, "little")
        + lat.to_bytes(4, "little", signed=True) + lon.to_bytes(4, "little", signed=True)
        + (2000).to_bytes(4, "little")
    )


async def read_contact(frame):
    dispatcher = MockDispatcher()
    await MessageReader(dispatcher).handle_rx(bytearray(frame))
    return dispatcher.dispatched_events[0].payload


@pytest.fixture
def handler():
    dispatcher = MagicMock()

    def subscribe(event_type, callback, attribute_filters=None):
        if event_type == EventType.OK:
            asyncio.get_event_loop().call_soon(callback, Event(event_type, {}))
        return MagicMock(spec=Subscription)

    dispatcher.subscribe = MagicMock(side_effect=subscribe)
    handler = CommandHandler()
    handler.sent = []

    async def sender(data):
        handler.sent.append(bytes(data))

    handler._sender_func = sender
    handler.dispatcher = dispatcher
    return handler


async def test_coordinates_are_written_back_as_read(handler):
    # two of the integers that int(value / 1e6 * 1e6) gives back one nearer zero
    contact = await read_contact(contact_frame(b"Node", 16000002, -2097148))

    await handler.update_contact(contact)

    frame = handler.sent[0]
    assert int.from_bytes(frame[LAT_AT:LAT_AT + 4], "little", signed=True) == 16000002
    assert int.from_bytes(frame[LAT_AT + 4:LAT_AT + 8], "little", signed=True) == -2097148


async def test_name_cut_mid_character_is_written_back_as_read(handler):
    # "Caf" and the first byte of the two that encode "é"
    name = b"Caf\xc3"
    contact = await read_contact(contact_frame(name, 0, 0))
    assert contact["adv_name"] == "Caf"

    await handler.update_contact(contact)

    assert handler.sent[0][NAME_AT:NAME_AT + 32] == name.ljust(32, b"\0")


async def test_a_changed_name_is_written(handler):
    contact = await read_contact(contact_frame(b"Caf\xc3", 0, 0))
    contact["adv_name"] = "Café"

    await handler.update_contact(contact)

    assert handler.sent[0][NAME_AT:NAME_AT + 32] == "Café".encode().ljust(32, b"\0")


async def test_lastmod_is_sent_when_given(handler):
    contact = await read_contact(contact_frame(b"Node", 0, 0))

    await handler.update_contact(contact)
    await handler.update_contact(contact, lastmod=2000)

    without, with_lastmod = handler.sent
    assert len(without) == LAT_AT + 8
    assert with_lastmod == without + (2000).to_bytes(4, "little")


async def test_set_coords_rounds(handler):
    await handler.set_coords(16000002 / 1e6, -2097148 / 1e6)

    frame = handler.sent[0]
    assert int.from_bytes(frame[1:5], "little", signed=True) == 16000002
    assert int.from_bytes(frame[5:9], "little", signed=True) == -2097148
