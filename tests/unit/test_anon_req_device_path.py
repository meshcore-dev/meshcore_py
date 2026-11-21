"""send_anon_req doesn't lose a path the device holds (#119: B4).

When meshcore's copy of a contact says flood, it reads the device's own record before changing it: a path the device
holds is used and left alone; a flood record is set to zero-hop and reset to flood after sending.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from meshcore.commands import CommandHandler
from meshcore.events import Event, EventType, Subscription

pytestmark = pytest.mark.asyncio

KEY = bytes(range(32))
ANON_REQ = b"\x39" + KEY + b"\x02"  # CMD_SEND_ANON_REQ, the key, AnonReqType.OWNER's value


def record(out_path_len, out_path="", hash_mode=0, name="Repeater"):
    """A contact as the reader reads it."""
    return {
        "public_key": KEY.hex(),
        "type": 2,
        "flags": 0,
        "out_path_len": out_path_len,
        "out_path_hash_mode": -1 if out_path_len == -1 else hash_mode,
        "out_path": out_path,
        "adv_name": name,
        "last_advert": 1000,
        "adv_lat": 0.0,
        "adv_lon": 0.0,
        "lastmod": 1000,
    }


@pytest.fixture
def handler():
    """A CommandHandler on a device that answers the request with MSG_SENT."""
    dispatcher = MagicMock()

    def subscribe(event_type, callback, attribute_filters=None):
        if event_type == EventType.MSG_SENT:
            payload = {"type": 0, "expected_ack": b"\x01\x02\x03\x04", "suggested_timeout": 4000}
            asyncio.get_event_loop().call_soon(callback, Event(event_type, payload))
        return MagicMock(spec=Subscription)

    dispatcher.subscribe = MagicMock(side_effect=subscribe)
    handler = CommandHandler()
    handler.sent = []

    async def sender(data):
        handler.sent.append(bytes(data))

    handler._sender_func = sender
    handler.dispatcher = dispatcher
    handler.change_contact_path = AsyncMock()
    handler.reset_path = AsyncMock()
    return handler


def holding(handler, copy, device_answer):
    handler._get_contact_by_prefix = MagicMock(return_value=copy)
    handler.get_contact_by_key = AsyncMock(return_value=device_answer)


@pytest.mark.parametrize(
    "device, reply_path",
    [
        (record(0), b"\x00"),
        (record(2, "aabb"), b"\x02" + bytes.fromhex("bbaa")),
    ],
    ids=["zero_hop", "two_hops"],
)
async def test_path_the_device_holds_is_used_and_left_alone(handler, device, reply_path):
    copy = record(-1)
    holding(handler, copy, Event(EventType.NEXT_CONTACT, device))

    result = await handler.send_anon_req(KEY, MagicMock(value=2))

    assert result.type == EventType.MSG_SENT
    handler.get_contact_by_key.assert_awaited_once_with(KEY)
    assert handler.sent == [ANON_REQ + reply_path]
    handler.change_contact_path.assert_not_awaited()
    handler.reset_path.assert_not_awaited()
    # meshcore's copy now has the device's path
    assert (copy["out_path_len"], copy["out_path"]) == (device["out_path_len"], device["out_path"])


async def test_flood_on_the_device_is_set_to_zero_hop_on_its_own_record_and_reset(handler):
    copy = record(-1, name="Old name")
    device = record(-1, name="Repeater")
    holding(handler, copy, Event(EventType.NEXT_CONTACT, device))

    await handler.send_anon_req(KEY, MagicMock(value=2))

    handler.change_contact_path.assert_awaited_once()
    assert handler.change_contact_path.await_args.args[0]["adv_name"] == "Repeater"
    assert handler.sent == [ANON_REQ + b"\x00"]
    handler.reset_path.assert_awaited_once()


async def test_contact_the_device_does_not_hold_is_not_added(handler):
    holding(handler, record(-1), Event(EventType.ERROR, {"error_code": 2}))

    result = await handler.send_anon_req(KEY, MagicMock(value=2))

    assert result.type == EventType.MSG_SENT
    assert handler.sent == [ANON_REQ + b"\x00"]
    handler.change_contact_path.assert_not_awaited()
    handler.reset_path.assert_not_awaited()


async def test_record_that_cannot_be_read_aborts_before_any_change(handler):
    holding(handler, record(-1), Event(EventType.ERROR, {"reason": "no_event_received"}))

    result = await handler.send_anon_req(KEY, MagicMock(value=2))

    assert result.is_error()
    assert result.payload["reason"] == "contact_read_failed"
    assert handler.sent == []
    handler.change_contact_path.assert_not_awaited()
    handler.reset_path.assert_not_awaited()


async def test_copy_with_a_path_is_not_read_again(handler):
    holding(handler, record(1, "cc"), None)

    await handler.send_anon_req(KEY, MagicMock(value=2))

    handler.get_contact_by_key.assert_not_awaited()
    assert handler.sent == [ANON_REQ + b"\x01" + bytes.fromhex("cc")]
