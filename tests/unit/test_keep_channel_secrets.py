"""An option to keep channel secrets out of the packet parser (#119: B7)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from Crypto.Hash import HMAC, SHA256

from meshcore import MeshCore
from meshcore.events import EventType
from meshcore.reader import MessageReader

pytestmark = pytest.mark.asyncio

SECRET = bytes(range(16))
CHANNEL_INFO = b"\x12\x01" + b"#test".ljust(32, b"\0") + SECRET


class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []

    async def dispatch(self, event):
        self.dispatched_events.append(event)


def group_post_log():
    """An RX_LOG_DATA frame carrying a flooded group post on SECRET's channel."""
    msg = bytes(16)
    mac = HMAC.new(SECRET, msg, digestmod=SHA256).digest()[:2]
    packet = bytes([0x05 << 2 | 0x01, 0x00]) + SHA256.new(SECRET).digest()[:1] + mac + msg
    return bytearray(b"\x88\x10\xc4" + packet)


async def rx_log(reader):
    reader.dispatcher.dispatched_events.clear()
    await reader.handle_rx(group_post_log())
    return reader.dispatcher.dispatched_events[0].payload


def held_secrets(reader):
    return [c["channel_secret"] for c in reader.packet_parser.channels if "channel_secret" in c]


async def test_secrets_kept_by_default():
    reader = MessageReader(MockDispatcher())

    await reader.handle_rx(bytearray(CHANNEL_INFO))

    assert held_secrets(reader) == [SECRET]
    assert (await rx_log(reader))["chan_name"] == "#test"


async def test_secrets_not_kept_when_turned_off():
    reader = MessageReader(MockDispatcher())
    reader.keep_channel_secrets = False

    await reader.handle_rx(bytearray(CHANNEL_INFO))

    event = reader.dispatcher.dispatched_events[0]
    assert event.type == EventType.CHANNEL_INFO
    assert event.payload["channel_secret"] == SECRET  # the caller still gets it
    assert held_secrets(reader) == []
    assert "chan_name" not in await rx_log(reader)


async def test_turning_it_off_drops_secrets_already_held():
    reader = MessageReader(MockDispatcher())
    await reader.handle_rx(bytearray(CHANNEL_INFO))
    await rx_log(reader)

    reader.keep_channel_secrets = False

    assert held_secrets(reader) == []
    assert reader.packet_parser.channels_log == []


async def test_meshcore_setter():
    cx = MagicMock()
    cx.send = AsyncMock()
    mc = MeshCore(cx)

    mc.set_keep_channel_secrets(False)

    assert mc._reader.packet_parser.keep_channel_secrets is False
