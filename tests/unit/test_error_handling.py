"""Verification tests for error response handling fixes.

The tests confirm that error responses are surfaced cleanly instead
of causing KeyError, TypeError, NameError, or silent fallthrough.
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from meshcore.commands import CommandHandler
from meshcore.events import EventType, Event, Subscription

pytestmark = pytest.mark.asyncio

VALID_PUBKEY_HEX = "0123456789abcdef" * 4  # 64 hex chars = 32 bytes


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def mock_connection():
    connection = MagicMock()
    connection.send = AsyncMock()
    return connection


@pytest.fixture
def mock_dispatcher():
    dispatcher = MagicMock()
    dispatcher.wait_for_event = AsyncMock()
    dispatcher.dispatch = AsyncMock()

    def fake_subscribe(event_type, handler, attribute_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        dispatcher._last_subscribe_handler = handler
        dispatcher._last_subscribe_event_type = event_type
        return sub

    dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)
    return dispatcher


@pytest.fixture
def command_handler(mock_connection, mock_dispatcher):
    handler = CommandHandler()

    async def sender(data):
        await mock_connection.send(data)

    handler._sender_func = sender
    handler.dispatcher = mock_dispatcher
    return handler


def setup_error_response(mock_dispatcher):
    """Configure dispatcher to return an ERROR event for any subscribe."""
    def fake_subscribe(evt_type, handler, attr_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        # Always fire ERROR regardless of which event type was subscribed
        if evt_type == EventType.ERROR:
            asyncio.get_event_loop().call_soon(
                handler, Event(EventType.ERROR, {"reason": "test_error"})
            )
        return sub

    mock_dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)


def setup_event_response(mock_dispatcher, event_type, payload):
    """Configure dispatcher to return a specific event."""
    def fake_subscribe(evt_type, handler, attr_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        if evt_type == event_type:
            asyncio.get_event_loop().call_soon(
                handler, Event(event_type, payload)
            )
        return sub

    mock_dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)


# ── Event.is_error() helper ──────────────────────────────────

async def test_event_is_error_true():
    """is_error() returns True for ERROR events."""
    event = Event(EventType.ERROR, {"reason": "test"})
    assert event.is_error() is True


async def test_event_is_error_false():
    """is_error() returns False for non-ERROR events."""
    event = Event(EventType.OK, {})
    assert event.is_error() is False
    event2 = Event(EventType.SELF_INFO, {"name": "test"})
    assert event2.is_error() is False


# ── send_msg_with_retry continues on ERROR ──────────────

async def test_send_msg_with_retry_error_no_keyerror(
    command_handler, mock_dispatcher
):
    """send_msg_with_retry returns None (exhausted retries) on
    persistent ERROR instead of raising KeyError on missing 'expected_ack'."""
    setup_error_response(mock_dispatcher)

    # Provide a mock contact so the path logic doesn't interfere
    command_handler._get_contact_by_prefix = MagicMock(return_value=None)

    # max_attempts=2 so it retries once then gives up
    result = await command_handler.send_msg_with_retry(
        VALID_PUBKEY_HEX, "hello", max_attempts=2, timeout=0.1
    )

    # Should return None (no ACK received) rather than raising KeyError
    assert result is None


# ── send_appstart includes ERROR in expected events ──────────

async def test_send_appstart_returns_error(
    command_handler, mock_dispatcher
):
    """send_appstart returns ERROR event instead of hanging on timeout."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.send_appstart()

    assert result.type == EventType.ERROR
    assert result.is_error() is True
    assert result.payload["reason"] == "test_error"


# ── device setters return ERROR from send_appstart ───────────

async def test_set_telemetry_mode_base_error(
    command_handler, mock_dispatcher
):
    """set_telemetry_mode_base returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_telemetry_mode_base(1)

    assert result.is_error()
    assert result.payload["reason"] == "test_error"


async def test_set_telemetry_mode_loc_error(
    command_handler, mock_dispatcher
):
    """set_telemetry_mode_loc returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_telemetry_mode_loc(1)

    assert result.is_error()


async def test_set_telemetry_mode_env_error(
    command_handler, mock_dispatcher
):
    """set_telemetry_mode_env returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_telemetry_mode_env(1)

    assert result.is_error()


async def test_set_manual_add_contacts_error(
    command_handler, mock_dispatcher
):
    """set_manual_add_contacts returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_manual_add_contacts(True)

    assert result.is_error()


async def test_set_advert_loc_policy_error(
    command_handler, mock_dispatcher
):
    """set_advert_loc_policy returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_advert_loc_policy(1)

    assert result.is_error()


async def test_set_multi_acks_error(
    command_handler, mock_dispatcher
):
    """set_multi_acks returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_multi_acks(1)

    assert result.is_error()


# ── send_anon_req falls back to zero-hop when no contact exists ─────────

async def test_send_anon_req_without_contact_sends_zero_hop(
    command_handler, mock_connection, mock_dispatcher
):
    """An unknown destination is sent with a zero-hop reply path.

    The contact is only used to build the reply path. Companion firmware from
    FIRMWARE_VER_CODE 13 synthesises a transient anon contact for an unknown
    pubkey, so refusing to send here would needlessly block probing any node
    the client has not already added. Must still not raise TypeError on the
    NoneType subscript that this test originally guarded.
    """
    command_handler._get_contact_by_prefix = MagicMock(return_value=None)
    command_handler.change_contact_path = AsyncMock()
    command_handler.reset_path = AsyncMock()
    setup_event_response(
        mock_dispatcher, EventType.MSG_SENT,
        {"expected_ack": b"\x01\x02\x03\x04", "suggested_timeout": 4000},
    )

    result = await command_handler.send_anon_req(
        VALID_PUBKEY_HEX, MagicMock(value=1)
    )

    assert not result.is_error()
    sent = mock_connection.send.await_args.args[0]
    # \x39 | 32-byte pubkey | request type | reply-path-len 0 (no path bytes)
    assert sent == b"\x39" + bytes.fromhex(VALID_PUBKEY_HEX) + b"\x01" + b"\x00"

    # No contact to mutate, so no device round-trips for path changes.
    command_handler.change_contact_path.assert_not_awaited()
    command_handler.reset_path.assert_not_awaited()


async def test_send_anon_req_without_contact_does_not_scale_timeout(
    command_handler, mock_dispatcher
):
    """suggested_timeout must not be multiplied by a path length we don't have."""
    command_handler._get_contact_by_prefix = MagicMock(return_value=None)
    reader = MagicMock()
    reader.register_binary_request = MagicMock()
    command_handler._reader = reader
    setup_event_response(
        mock_dispatcher, EventType.MSG_SENT,
        {"expected_ack": b"\x01\x02\x03\x04", "suggested_timeout": 4000},
    )

    result = await command_handler.send_anon_req(
        VALID_PUBKEY_HEX, MagicMock(value=1)
    )

    # out_path_len 0 -> (0 + 1) -> unchanged from the device's own estimate.
    assert result.payload["suggested_timeout"] == 4000
    reader.register_binary_request.assert_called_once()


async def test_send_anon_req_with_contact_still_uses_its_path(
    command_handler, mock_connection, mock_dispatcher
):
    """A known contact's reply path and timeout scaling are both unchanged.

    _reader must be set: the out_path_len-based timeout scaling is gated behind
    it, and that scaling is the only behaviour the no-contact refactor touches on
    this path -- without a reader it is never executed.
    """
    command_handler._get_contact_by_prefix = MagicMock(return_value={
        "public_key": VALID_PUBKEY_HEX,
        "out_path_len": 3,
        "out_path": "aabbcc",
    })
    command_handler.change_contact_path = AsyncMock()
    command_handler.reset_path = AsyncMock()
    reader = MagicMock()
    command_handler._reader = reader
    setup_event_response(
        mock_dispatcher, EventType.MSG_SENT,
        {"expected_ack": b"\x01\x02\x03\x04", "suggested_timeout": 4000},
    )

    result = await command_handler.send_anon_req(VALID_PUBKEY_HEX, MagicMock(value=1))

    sent = mock_connection.send.await_args.args[0]
    # \x39 | pubkey | request type | reply-path-len 3 | path reversed
    assert sent == (
        b"\x39" + bytes.fromhex(VALID_PUBKEY_HEX) + b"\x01"
        + b"\x03" + bytes.fromhex("ccbbaa")
    )
    # Scaled by out_path_len + 1 = 4.
    assert result.payload["suggested_timeout"] == 16000
    reader.register_binary_request.assert_called_once()
    assert reader.register_binary_request.call_args.args[3] == 16000 / 800.0
    command_handler.change_contact_path.assert_not_awaited()
    command_handler.reset_path.assert_not_awaited()


async def test_send_anon_req_timeout_uses_path_len_as_sent(
    command_handler, mock_connection, mock_dispatcher
):
    """The timeout multiplier must match the path length actually transmitted.

    The contact dict is a live reference that other commands mutate in place, so
    re-reading it after the await could scale the timeout by a path length that
    was never sent.
    """
    contact = {"public_key": VALID_PUBKEY_HEX, "out_path_len": 3, "out_path": "aabbcc"}
    command_handler._get_contact_by_prefix = MagicMock(return_value=contact)
    command_handler._reader = MagicMock()

    def fake_subscribe(evt_type, handler, attr_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        if evt_type == EventType.MSG_SENT:
            # Simulate another command flipping the contact to flood mid-send.
            contact["out_path_len"] = -1
            contact["out_path"] = ""
            asyncio.get_event_loop().call_soon(
                handler,
                Event(EventType.MSG_SENT,
                      {"expected_ack": b"\x01\x02\x03\x04", "suggested_timeout": 4000}),
            )
        return sub

    mock_dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)

    result = await command_handler.send_anon_req(VALID_PUBKEY_HEX, MagicMock(value=1))

    sent = mock_connection.send.await_args.args[0]
    assert sent.endswith(b"\x03" + bytes.fromhex("ccbbaa"))
    # 4 x 4000, matching the 3-hop path in the frame -- not 0 from the mutated -1.
    assert result.payload["suggested_timeout"] == 16000


async def test_send_anon_req_flood_contact_still_forces_and_restores_zero_hop(
    command_handler, mock_connection, mock_dispatcher
):
    """out_path_len == -1 keeps its existing force-zero-hop-then-restore path."""
    contact = {
        "public_key": VALID_PUBKEY_HEX,
        "out_path_len": -1,
        "out_path": "",
    }

    async def fake_change_path(c, path):
        # update_contact() reflects the change onto the dict; -1 would otherwise
        # raise OverflowError on the unsigned to_bytes below.
        c["out_path_len"] = 0
        c["out_path"] = ""

    command_handler._get_contact_by_prefix = MagicMock(return_value=contact)
    command_handler.change_contact_path = AsyncMock(side_effect=fake_change_path)
    command_handler.reset_path = AsyncMock()
    setup_event_response(
        mock_dispatcher, EventType.MSG_SENT,
        {"expected_ack": b"\x01\x02\x03\x04", "suggested_timeout": 4000},
    )

    await command_handler.send_anon_req(VALID_PUBKEY_HEX, MagicMock(value=1))

    command_handler.change_contact_path.assert_awaited_once()
    command_handler.reset_path.assert_awaited_once()
    sent = mock_connection.send.await_args.args[0]
    assert sent == b"\x39" + bytes.fromhex(VALID_PUBKEY_HEX) + b"\x01" + b"\x00"


async def test_send_anon_req_survives_change_contact_path_not_mutating(
    command_handler, mock_connection, mock_dispatcher
):
    """A failed change_contact_path must not crash and must still restore the path.

    update_contact() normally writes out_path_len back onto the dict, but if it
    errors the value stays -1. Unclamped, the unsigned to_bytes raises
    OverflowError, which skips reset_path and leaves the contact pinned to
    zero-hop on the device.
    """
    contact = {"public_key": VALID_PUBKEY_HEX, "out_path_len": -1, "out_path": ""}
    command_handler._get_contact_by_prefix = MagicMock(return_value=contact)
    # Returns an error without reflecting the change onto the dict.
    command_handler.change_contact_path = AsyncMock(
        return_value=Event(EventType.ERROR, {"reason": "device_query_failed"})
    )
    command_handler.reset_path = AsyncMock()
    setup_event_response(
        mock_dispatcher, EventType.MSG_SENT,
        {"expected_ack": b"\x01\x02\x03\x04", "suggested_timeout": 4000},
    )

    result = await command_handler.send_anon_req(VALID_PUBKEY_HEX, MagicMock(value=1))

    assert not result.is_error()
    sent = mock_connection.send.await_args.args[0]
    assert sent == b"\x39" + bytes.fromhex(VALID_PUBKEY_HEX) + b"\x01" + b"\x00"
    command_handler.reset_path.assert_awaited_once()


# ── send_trace handles unknown path_hash_len without NameError ──

async def test_send_trace_unknown_path_hash_len(
    command_handler, mock_connection, mock_dispatcher
):
    """send_trace with a path whose segments don't match any known
    path_hash_len returns ERROR cleanly instead of NameError on 'e'."""
    # 5-char hex segments → path_hash_len = 2.5 → doesn't match 1,2,4,8
    result = await command_handler.send_trace(
        auth_code=0, tag=1, flags=None, path="abcde"
    )

    assert result.is_error()
    assert result.payload["reason"] == "invalid_path_format"


# ── BLE transport serialises writes ──────────────────────────

async def test_ble_send_serialises_concurrent_writes():
    """Overlapping write_gatt_char() calls must not interleave.

    Two concurrent writes to the same characteristic drop the link outright
    (observed on macOS/CoreBluetooth: "BLE write failed: 19"). Nothing above the
    transport guarantees callers are sequential, so the transport must.
    """
    from meshcore.ble_cx import BLEConnection

    conn = BLEConnection.__new__(BLEConnection)   # bypass bleak availability check
    conn._disconnect_callback = None
    conn._write_lock = None
    conn.rx_char = object()

    overlap = {"current": 0, "max": 0}

    class FakeClient:
        async def write_gatt_char(self, char, data, response=True):
            overlap["current"] += 1
            overlap["max"] = max(overlap["max"], overlap["current"])
            await asyncio.sleep(0.01)     # a real write is not instantaneous
            overlap["current"] -= 1

    conn.client = FakeClient()

    await asyncio.gather(*(conn.send(b"\x01\x02") for _ in range(8)))

    assert overlap["max"] == 1, f"{overlap['max']} writes overlapped"


async def test_ble_send_releases_lock_on_write_failure():
    """A failed write must not wedge the lock for every later command."""
    from meshcore.ble_cx import BLEConnection

    conn = BLEConnection.__new__(BLEConnection)
    conn._write_lock = None
    conn.rx_char = object()
    reasons = []

    async def capture(reason):
        reasons.append(reason)

    conn._disconnect_callback = capture

    class BoomThenOK:
        def __init__(self):
            self.calls = 0

        async def write_gatt_char(self, char, data, response=True):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("19")

    conn.client = BoomThenOK()

    await conn.send(b"\x01")
    assert reasons == ["ble_write_failed: 19"]
    # Second write must still be able to acquire the lock.
    await asyncio.wait_for(conn.send(b"\x02"), timeout=1.0)
    assert conn.client.calls == 2


# ── reply-path encoding (hash mode + hop-wise reversal) ──────

from meshcore.commands.base import encode_reply_path  # noqa: E402


async def test_encode_reply_path_zero_hop():
    # len 0, mode 0 -> a single 0x00 byte, the zero-hop direct request.
    assert encode_reply_path(0, "", 0) == b"\x00"


async def test_encode_reply_path_mode0_reverses_hops():
    # hops aa, bb -> reply visits bb then aa. Mode 0 leaves the top bits clear.
    assert encode_reply_path(2, "aabb", 0) == b"\x02" + bytes.fromhex("bbaa")


async def test_encode_reply_path_carries_hash_mode_in_top_bits():
    """The server reads hash size from bits 6-7; omitting it truncates each hop.

    Mode 2 = 3 bytes per hop. Without the mode the server would read hash_size 1
    and reply to two 1-byte hops that do not exist.
    """
    out = encode_reply_path(2, "aabbccddeeff", 2)
    assert out[0] == 0x82                      # 2 hops | (mode 2 << 6)
    assert out[0] & 63 == 2                    # server: reply_path_len
    assert (out[0] >> 6) + 1 == 3              # server: reply_path_hash_size
    # Hop order reversed, each 3-byte hash intact.
    assert out[1:] == bytes.fromhex("ddeeff") + bytes.fromhex("aabbcc")


async def test_encode_reply_path_mode1_two_byte_hops():
    out = encode_reply_path(3, "aabbccddeeff", 1)
    assert out[0] == (3 | (1 << 6))
    assert out[1:] == bytes.fromhex("eeff") + bytes.fromhex("ccdd") + bytes.fromhex("aabb")


async def test_encode_reply_path_flood_mode_is_clamped():
    # out_path_hash_mode is -1 for a flood contact; must not produce a negative shift.
    assert encode_reply_path(0, "", -1) == b"\x00"


async def test_encode_reply_path_ignores_padding_beyond_the_path():
    # Real device fields are NUL-padded to 64 bytes; only the used hops count.
    padded = "aabb" + "00" * 60
    assert encode_reply_path(2, padded, 0) == b"\x02" + bytes.fromhex("bbaa")


async def test_encode_reply_path_truncated_field_does_not_emit_short_hops():
    # Claims 4 hops of 3 bytes but only 6 bytes present -> emit the 2 it has.
    out = encode_reply_path(4, "aabbccddeeff", 2)
    assert out[0] & 63 == 2
    assert out[1:] == bytes.fromhex("ddeeff") + bytes.fromhex("aabbcc")


async def test_send_anon_req_reply_path_uses_hash_mode(
    command_handler, mock_connection, mock_dispatcher
):
    """End-to-end: a mode-2 multi-hop contact must get a correct reply path."""
    command_handler._get_contact_by_prefix = MagicMock(return_value={
        "public_key": VALID_PUBKEY_HEX,
        "out_path_len": 2,
        "out_path": "aabbccddeeff",
        "out_path_hash_mode": 2,
    })
    command_handler.change_contact_path = AsyncMock()
    command_handler.reset_path = AsyncMock()
    setup_event_response(
        mock_dispatcher, EventType.MSG_SENT,
        {"expected_ack": b"\x01\x02\x03\x04", "suggested_timeout": 4000},
    )

    await command_handler.send_anon_req(VALID_PUBKEY_HEX, MagicMock(value=1))

    sent = mock_connection.send.await_args.args[0]
    assert sent == (
        b"\x39" + bytes.fromhex(VALID_PUBKEY_HEX) + b"\x01"
        + b"\x82" + bytes.fromhex("ddeeff") + bytes.fromhex("aabbcc")
    )


async def test_reader_contact_out_path_keeps_zero_bytes():
    """A hop hash containing 0x00 must survive parsing by the real reader.

    The 64-byte field is NUL-padded, but stripping every NUL also eats
    legitimate hash bytes, shortening the path and shifting every hop after it.
    """
    from meshcore.reader import MessageReader
    from meshcore.packets import PacketType

    hops = bytes.fromhex("aa00bb")           # middle byte is a legitimate 0x00
    frame = (
        bytes([PacketType.CONTACT.value])
        + bytes(32)                          # public_key
        + b"\x02"                            # type
        + b"\x00"                            # flags
        + bytes([1 | (2 << 6)])              # 1 hop, hash mode 2 -> 3 bytes/hop
        + hops + bytes(64 - len(hops))       # out_path, NUL-padded to 64
        + b"name".ljust(32, b"\0")           # adv_name
        + (0).to_bytes(4, "little")          # last_advert
        + (0).to_bytes(4, "little", signed=True)   # adv_lat
        + (0).to_bytes(4, "little", signed=True)   # adv_lon
        + (0).to_bytes(4, "little")          # lastmod
    )

    seen = []

    class Dispatcher:
        async def dispatch(self, event):
            seen.append(event)

    reader = MessageReader(Dispatcher())
    reader.contacts = {}
    await reader.handle_rx(frame)

    contact = next(e.payload for e in seen if e.type == EventType.NEXT_CONTACT)
    assert contact["out_path_len"] == 1
    assert contact["out_path_hash_mode"] == 2
    assert contact["out_path"] == "aa00bb", "the 0x00 inside the hop hash was lost"
