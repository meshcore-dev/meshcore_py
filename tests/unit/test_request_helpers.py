"""Request helpers for GET_OWNER_INFO, SUBSCRIBE and UNSUBSCRIBE (#119: B8)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from meshcore.commands import CommandHandler
from meshcore.events import Event, EventType, Subscription

pytestmark = pytest.mark.asyncio

KEY = bytes(range(32))
TAG = b"\x01\x02\x03\x04"


def answering(response_data):
    """A CommandHandler on a device that answers the request with MSG_SENT,
    and the node with a BINARY_RESPONSE carrying response_data (None: no
    answer)."""
    dispatcher = MagicMock()

    def subscribe(event_type, callback, attribute_filters=None):
        if event_type == EventType.MSG_SENT:
            payload = {"type": 0, "expected_ack": TAG, "suggested_timeout": 4000}
            asyncio.get_event_loop().call_soon(callback, Event(event_type, payload))
        return MagicMock(spec=Subscription)

    dispatcher.subscribe = MagicMock(side_effect=subscribe)
    answer = None
    if response_data is not None:
        answer = Event(EventType.BINARY_RESPONSE, {"tag": TAG.hex(), "data": response_data.hex()})
    dispatcher.wait_for_event = AsyncMock(return_value=answer)

    handler = CommandHandler()
    handler.sent = []

    async def sender(data):
        handler.sent.append(bytes(data))

    handler._sender_func = sender
    handler.dispatcher = dispatcher
    return handler


async def test_owner_info():
    # as simple_repeater writes it: sprintf("%s\n%s\n%s"), padded to the cipher block
    handler = answering(b"v1.18.0\nRepeater\nOwner: Jo\nCall 123" + bytes(5))

    result = await handler.req_owner_info_sync(KEY.hex())

    assert handler.sent == [b"\x32" + KEY + b"\x07"]
    assert result == {"firmware_version": "v1.18.0", "name": "Repeater", "owner": "Owner: Jo\nCall 123"}
    assert handler.dispatcher.wait_for_event.await_args.kwargs["attribute_filters"] == {"tag": TAG.hex()}


async def test_owner_info_no_answer():
    assert await answering(None).req_owner_info_sync(KEY.hex()) is None


async def test_subscribe():
    # expiry 600 s, reserved, then the scope's name
    handler = answering((600).to_bytes(2, "little") + b"\0\0" + b"#au-vic" + bytes(3))
    deltas = bytes.fromhex("01670005")  # channel 1, temperature, 0.5 C

    result = await handler.req_subscribe_sync(KEY.hex(), b"\xaa\xbb\xcc\xdd", 600, deltas)

    assert handler.sent == [
        b"\x32" + KEY + b"\x08" + b"\xaa\xbb\xcc\xdd" + (600).to_bytes(2, "little") + b"\x00\x04" + deltas
    ]
    assert result == {"expiry_secs": 600, "scope": "#au-vic"}


async def test_subscribe_refused():
    result = await answering(bytes(4)).req_subscribe_sync(KEY.hex(), TAG, 600, bytes(3))

    assert result == {"expiry_secs": 0, "scope": ""}


@pytest.mark.parametrize("push_tag, deltas", [(b"\x01\x02\x03", bytes(3)), (TAG, bytes(2)), (TAG, bytes(15))])
async def test_subscribe_rejects_what_the_sensor_would(push_tag, deltas):
    handler = answering(bytes(4))

    with pytest.raises(ValueError):
        await handler.req_subscribe_sync(KEY.hex(), push_tag, 600, deltas)
    assert handler.sent == []


async def test_unsubscribe():
    handler = answering(bytes(8) + b"\x5a\xa5")

    assert await handler.req_unsubscribe_sync(KEY.hex()) is True
    assert handler.sent == [b"\x32" + KEY + b"\x09"]
