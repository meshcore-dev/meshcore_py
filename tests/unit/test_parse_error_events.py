"""A reply that can't be read is reported to the waiting caller (#119: A5)."""
import asyncio

import pytest

from meshcore.commands import CommandHandler
from meshcore.events import EventDispatcher, EventType
from meshcore.reader import MessageReader

pytestmark = pytest.mark.asyncio


class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []

    async def dispatch(self, event):
        self.dispatched_events.append(event)


async def _events(frame):
    dispatcher = MockDispatcher()
    await MessageReader(dispatcher).handle_rx(bytearray(frame))
    return dispatcher.dispatched_events


async def test_unreadable_reply_dispatches_parse_error():
    # CHANNEL_MSG_RECV_V3 cut after its reserved bytes, before channel_idx
    events = await _events(bytes.fromhex("11100000"))

    assert [e.type for e in events] == [EventType.ERROR]
    assert events[0].payload == {"reason": "parse_error", "packet_type": 0x11}


async def test_short_channel_data_reply_dispatches_invalid_frame_length():
    events = await _events(bytes([0x1B]) + bytes(7))

    assert [e.type for e in events] == [EventType.ERROR]
    assert events[0].payload == {"reason": "invalid_frame_length", "packet_type": 0x1B}


async def test_unreadable_push_dispatches_nothing():
    # TRACE_DATA (a push) cut after its reserved byte
    events = await _events(bytes([0x89, 0x00]))

    assert events == []


async def test_waiting_caller_gets_the_error_instead_of_timing_out():
    dispatcher = EventDispatcher()
    await dispatcher.start()
    reader = MessageReader(dispatcher)
    handler = CommandHandler()
    handler.set_dispatcher(dispatcher)

    async def radio(data):
        # the radio answers SYNC_NEXT_MESSAGE with a reply cut short
        asyncio.get_running_loop().call_soon(
            asyncio.ensure_future, reader.handle_rx(bytearray.fromhex("11100000"))
        )

    handler._sender_func = radio
    try:
        result = await handler.send(
            b"\x0a", [EventType.CHANNEL_MSG_RECV, EventType.ERROR], timeout=2
        )
    finally:
        await dispatcher.stop()

    assert result.type == EventType.ERROR
    assert result.payload == {"reason": "parse_error", "packet_type": 0x11}
