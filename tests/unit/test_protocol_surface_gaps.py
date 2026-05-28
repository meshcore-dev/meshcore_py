"""Verification tests for protocol surface gaps.

Each test constructs a mock firmware frame and verifies the SDK dispatches
the correct EventType with the expected payload fields.
"""

import asyncio
import struct
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from meshcore.events import Event, EventType, EventDispatcher
from meshcore.reader import MessageReader
from meshcore.packets import PacketType, CommandType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reader():
    """Create a MessageReader with a mock dispatcher that records dispatched events."""
    dispatcher = MagicMock(spec=EventDispatcher)
    dispatched = []

    async def _capture(event):
        dispatched.append(event)

    dispatcher.dispatch = AsyncMock(side_effect=_capture)
    reader = MessageReader(dispatcher)
    return reader, dispatched


# ---------------------------------------------------------------------------
# CONTACT_DELETED handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contact_deleted_dispatches_event():
    """A 33-byte CONTACT_DELETED frame dispatches EventType.CONTACT_DELETED."""
    reader, dispatched = _make_reader()
    pubkey = bytes(range(32))
    frame = bytes([PacketType.CONTACT_DELETED.value]) + pubkey
    assert len(frame) == 33

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.CONTACT_DELETED
    assert evt.payload["pubkey"] == pubkey.hex()
    assert evt.attributes["pubkey"] == pubkey.hex()


@pytest.mark.asyncio
async def test_contact_deleted_short_frame_ignored():
    """A CONTACT_DELETED frame shorter than 33 bytes is silently dropped."""
    reader, dispatched = _make_reader()
    # Only 10 bytes — too short
    frame = bytes([PacketType.CONTACT_DELETED.value]) + b"\x00" * 9

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 0


# ---------------------------------------------------------------------------
# CONTACTS_FULL handler + enum entry
# ---------------------------------------------------------------------------

def test_contacts_full_enum_exists():
    """PacketType.CONTACTS_FULL == 0x90."""
    assert PacketType.CONTACTS_FULL.value == 0x90


@pytest.mark.asyncio
async def test_contacts_full_dispatches_event():
    """A 1-byte CONTACTS_FULL push dispatches EventType.CONTACTS_FULL."""
    reader, dispatched = _make_reader()
    frame = bytes([PacketType.CONTACTS_FULL.value])

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.CONTACTS_FULL
    assert evt.payload == {}


# ---------------------------------------------------------------------------
# TUNING_PARAMS handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tuning_params_dispatches_event():
    """A 9-byte TUNING_PARAMS frame dispatches with rx_delay and airtime_factor."""
    reader, dispatched = _make_reader()
    rx_delay = 500
    airtime_factor = 200
    frame = (
        bytes([PacketType.TUNING_PARAMS.value])
        + rx_delay.to_bytes(4, "little")
        + airtime_factor.to_bytes(4, "little")
    )
    assert len(frame) == 9

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.TUNING_PARAMS
    assert evt.payload["rx_delay"] == 500
    assert evt.payload["airtime_factor"] == 200


@pytest.mark.asyncio
async def test_tuning_params_short_frame_dispatches_error():
    """A TUNING_PARAMS frame shorter than 9 bytes dispatches ERROR."""
    reader, dispatched = _make_reader()
    # Only 5 bytes — too short
    frame = bytes([PacketType.TUNING_PARAMS.value]) + b"\x01\x00\x00\x00"

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.ERROR
    assert evt.payload["reason"] == "invalid_frame_length"


# ---------------------------------------------------------------------------
# send_trace() one-byte pad
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_trace_empty_path_pads_to_11_bytes():
    """send_trace() with no path produces an 11-byte packet (not 10)."""
    from meshcore.commands.messaging import MessagingCommands

    cmd = MessagingCommands.__new__(MessagingCommands)

    captured_data = None

    async def mock_send(data, expected_events, timeout=None):
        nonlocal captured_data
        captured_data = bytes(data)
        return Event(EventType.MSG_SENT, {"type": 0, "expected_ack": b"\x00" * 4, "suggested_timeout": 1000})

    cmd.send = mock_send

    await cmd.send_trace(auth_code=0, tag=1, flags=0, path=None)

    assert captured_data is not None
    # cmd(1) + tag(4) + auth(4) + flags(1) + pad(1) = 11
    assert len(captured_data) == 11
    assert captured_data[-1] == 0x00  # The pad byte


@pytest.mark.asyncio
async def test_send_trace_with_path_no_padding():
    """send_trace() with a non-empty path does NOT add padding."""
    from meshcore.commands.messaging import MessagingCommands

    cmd = MessagingCommands.__new__(MessagingCommands)

    captured_data = None

    async def mock_send(data, expected_events, timeout=None):
        nonlocal captured_data
        captured_data = bytes(data)
        return Event(EventType.MSG_SENT, {"type": 0, "expected_ack": b"\x00" * 4, "suggested_timeout": 1000})

    cmd.send = mock_send

    # 2-byte path hash (flags=1 means hash_len=2)
    await cmd.send_trace(auth_code=0, tag=1, flags=1, path=b"\xAA\xBB")

    assert captured_data is not None
    # cmd(1) + tag(4) + auth(4) + flags(1) + path(2) = 12 — no pad needed
    assert len(captured_data) == 12


# ---------------------------------------------------------------------------
# Command wrapper: send_raw_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_raw_data_wrapper():
    """send_raw_data sends CMD 0x19 + payload."""
    from meshcore.commands.messaging import MessagingCommands

    cmd = MessagingCommands.__new__(MessagingCommands)

    captured_data = None

    async def mock_send(data, expected_events, timeout=None):
        nonlocal captured_data
        captured_data = bytes(data)
        return Event(EventType.MSG_SENT, {"type": 0, "expected_ack": b"\x00" * 4, "suggested_timeout": 1000})

    cmd.send = mock_send

    await cmd.send_raw_data(b"\xDE\xAD")

    assert captured_data is not None
    assert captured_data[0] == 0x19  # CMD_SEND_RAW_DATA
    assert captured_data[1:] == b"\xDE\xAD"


# ---------------------------------------------------------------------------
# Command wrapper: has_connection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_has_connection_wrapper():
    """has_connection sends CMD 0x1c."""
    from meshcore.commands.device import DeviceCommands

    cmd = DeviceCommands.__new__(DeviceCommands)

    captured_data = None

    async def mock_send(data, expected_events, timeout=None):
        nonlocal captured_data
        captured_data = bytes(data)
        return Event(EventType.OK, {"value": 1})

    cmd.send = mock_send

    await cmd.has_connection()

    assert captured_data is not None
    assert captured_data == b"\x1c"


# ---------------------------------------------------------------------------
# Command wrapper: get_tuning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tuning_wrapper():
    """get_tuning sends CMD 0x2b (GET_TUNING_PARAMS = 43)."""
    from meshcore.commands.device import DeviceCommands

    cmd = DeviceCommands.__new__(DeviceCommands)

    captured_data = None

    async def mock_send(data, expected_events, timeout=None):
        nonlocal captured_data
        captured_data = bytes(data)
        return Event(EventType.TUNING_PARAMS, {"rx_delay": 500, "airtime_factor": 200})

    cmd.send = mock_send

    result = await cmd.get_tuning()

    assert captured_data == b"\x2b"
    assert result.type == EventType.TUNING_PARAMS


# ---------------------------------------------------------------------------
# Command wrapper: get_contact_by_key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_contact_by_key_wrapper():
    """get_contact_by_key sends CMD 0x1e + 32-byte pubkey."""
    from meshcore.commands.contact import ContactCommands

    cmd = ContactCommands.__new__(ContactCommands)

    captured_data = None

    async def mock_send(data, expected_events, timeout=None):
        nonlocal captured_data
        captured_data = bytes(data)
        return Event(EventType.NEXT_CONTACT, {"public_key": "ab" * 32})

    cmd.send = mock_send

    pubkey = bytes(range(32))
    await cmd.get_contact_by_key(pubkey)

    assert captured_data is not None
    assert captured_data[0] == 0x1E  # CMD_GET_CONTACT_BY_KEY
    assert captured_data[1:] == pubkey


# ---------------------------------------------------------------------------
# Command wrapper: factory_reset (two-step)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_factory_reset_two_step():
    """factory_reset requires a token from request_factory_reset."""
    from meshcore.commands.device import DeviceCommands

    cmd = DeviceCommands.__new__(DeviceCommands)

    captured_data = None

    async def mock_send(data, expected_events, timeout=None):
        nonlocal captured_data
        captured_data = bytes(data)
        return Event(EventType.OK, {})

    cmd.send = mock_send

    # Step 1: request token
    token = await cmd.request_factory_reset()
    assert isinstance(token, str)
    assert len(token) == 16  # hex-encoded 8 bytes

    # Step 2: confirm with wrong token fails
    with pytest.raises(ValueError, match="Invalid or expired"):
        await cmd.confirm_factory_reset("wrong_token")

    # Step 2: confirm with correct token succeeds
    await cmd.confirm_factory_reset(token)
    assert captured_data == b"\x33"  # CMD_FACTORY_RESET


@pytest.mark.asyncio
async def test_factory_reset_without_request_fails():
    """confirm_factory_reset without request_factory_reset raises ValueError."""
    from meshcore.commands.device import DeviceCommands

    cmd = DeviceCommands.__new__(DeviceCommands)

    with pytest.raises(ValueError, match="Invalid or expired"):
        await cmd.confirm_factory_reset("any_token")


# ---------------------------------------------------------------------------
# GET_STATS enum entry
# ---------------------------------------------------------------------------

def test_get_stats_enum_exists():
    """CommandType.GET_STATS == 56."""
    assert CommandType.GET_STATS.value == 56


@pytest.mark.asyncio
async def test_get_stats_core_uses_enum():
    """get_stats_core sends CommandType.GET_STATS.value (0x38) + 0x00."""
    from meshcore.commands.device import DeviceCommands

    cmd = DeviceCommands.__new__(DeviceCommands)

    captured_data = None

    async def mock_send(data, expected_events, timeout=None):
        nonlocal captured_data
        captured_data = bytes(data)
        return Event(EventType.STATS_CORE, {})

    cmd.send = mock_send

    await cmd.get_stats_core()

    assert captured_data is not None
    assert captured_data[0] == CommandType.GET_STATS.value  # 0x38 = 56
    assert captured_data[1] == 0x00


# ---------------------------------------------------------------------------
# CHANNEL_DATA_RECV handler + enum entry (group-channel binary data)
# ---------------------------------------------------------------------------

def test_channel_data_recv_enum_exists():
    """PacketType.CHANNEL_DATA_RECV == 27 (the previously-skipped enum slot)."""
    assert PacketType.CHANNEL_DATA_RECV.value == 27


@pytest.mark.asyncio
async def test_channel_data_recv_direct_path_frame():
    """A realistic direct-path CHANNEL_DATA_RECV frame dispatches the typed payload.

    Frame: code + snr(0x10) + reserved(00 00) + channel_idx(1)
           + path_len(0xFF direct) + data_type(0x0123 LE) + data_len(4)
           + payload(DEADBEEF).
    """
    reader, dispatched = _make_reader()
    frame = bytes([
        PacketType.CHANNEL_DATA_RECV.value,
        0x10,              # SNR (signed int8) -> 16 / 4 = 4.0
        0x00, 0x00,        # reserved
        0x01,              # channel_idx
        0xFF,              # path_len sentinel -> direct message
        0x23, 0x01,        # data_type = 0x0123 (uint16 little-endian)
        0x04,              # data_len
        0xDE, 0xAD, 0xBE, 0xEF,  # payload
    ])
    assert len(frame) == 13

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.CHANNEL_DATA_RECV
    assert evt.payload["SNR"] == 4.0
    assert evt.payload["channel_idx"] == 1
    assert evt.payload["path_len"] == 255
    assert evt.payload["path_hash_mode"] == -1
    assert evt.payload["data_type"] == 0x0123
    assert evt.payload["data_len"] == 4
    assert evt.payload["payload"] == "deadbeef"
    assert evt.attributes["channel_idx"] == 1
    assert evt.attributes["data_type"] == 0x0123


@pytest.mark.asyncio
async def test_channel_data_recv_route_flood_path_len_bits():
    """A route-flood path_len byte splits into hash-mode (>>6) and length (&0x3F).

    path_len = 0x42 = 0b01000010 -> hash_mode = 1, length = 2.
    """
    reader, dispatched = _make_reader()
    frame = bytes([
        PacketType.CHANNEL_DATA_RECV.value,
        0x10,              # SNR
        0x00, 0x00,        # reserved
        0x02,              # channel_idx
        0x42,              # path_len -> hash_mode 1, length 2
        0x00, 0x00,        # data_type = 0
        0x02,              # data_len
        0xAA, 0xBB,        # payload
    ])
    assert len(frame) == 11

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.CHANNEL_DATA_RECV
    assert evt.payload["path_hash_mode"] == 1
    assert evt.payload["path_len"] == 2
    assert evt.payload["channel_idx"] == 2
    assert evt.payload["data_type"] == 0
    assert evt.payload["data_len"] == 2
    assert evt.payload["payload"] == "aabb"


@pytest.mark.asyncio
async def test_channel_data_recv_under_minimum_frame_ignored():
    """A CHANNEL_DATA_RECV frame shorter than the 9-byte header is dropped."""
    reader, dispatched = _make_reader()
    # 8 bytes total (header needs 9) — missing the data_len byte.
    frame = bytes([
        PacketType.CHANNEL_DATA_RECV.value,
        0x10, 0x00, 0x00, 0x01, 0xFF, 0x00, 0x00,
    ])
    assert len(frame) == 8

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 0


@pytest.mark.asyncio
async def test_channel_data_recv_widened_data_type():
    """data_type is a 16-bit field: a value > 0xFF round-trips through the 2-byte read.

    data_type = 0x0201 (513) confirms the high byte is not truncated. data_len = 0
    exercises the empty-payload tail.
    """
    reader, dispatched = _make_reader()
    frame = bytes([
        PacketType.CHANNEL_DATA_RECV.value,
        0x10,              # SNR
        0x00, 0x00,        # reserved
        0x00,              # channel_idx
        0xFF,              # path_len direct
        0x01, 0x02,        # data_type = 0x0201 (little-endian)
        0x00,              # data_len = 0
    ])
    assert len(frame) == 9

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.CHANNEL_DATA_RECV
    assert evt.payload["data_type"] == 0x0201
    assert evt.payload["data_type"] > 0xFF
    assert evt.payload["data_len"] == 0
    assert evt.payload["payload"] == ""


# ---------------------------------------------------------------------------
# Wire-format parity bundle: AUTOADD_CONFIG (max_hops trailing byte)
# ---------------------------------------------------------------------------
# AUTOADD_CONFIG firmware emits 1 byte (legacy) or 2 bytes (companion-v1.14.0+,
# commit 00566741, adds `max_hops`). The SDK had been silently dropping the
# trailing byte. These pairs verify the defensive trailing-field read.

@pytest.mark.asyncio
async def test_autoadd_config_legacy_one_byte_frame():
    """Legacy 1-byte AUTOADD_CONFIG frame: only `config` key present."""
    reader, dispatched = _make_reader()
    frame = bytes([PacketType.AUTOADD_CONFIG.value, 0x01])  # code + config=1

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.AUTOADD_CONFIG
    assert evt.payload == {"config": 1}
    assert "max_hops" not in evt.payload


@pytest.mark.asyncio
async def test_autoadd_config_modern_two_byte_frame():
    """Modern 2-byte AUTOADD_CONFIG frame (companion-v1.14.0+): `config` + `max_hops`."""
    reader, dispatched = _make_reader()
    frame = bytes([PacketType.AUTOADD_CONFIG.value, 0x01, 0x10])  # code + config=1 + max_hops=16

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.AUTOADD_CONFIG
    assert evt.payload == {"config": 1, "max_hops": 16}


# ---------------------------------------------------------------------------
# Wire-format parity bundle: LOGIN_SUCCESS (3 trailing fields)
# ---------------------------------------------------------------------------
# Firmware emits an 8-byte legacy frame ("OK" path) or a 14-byte modern frame
# (RESP_SERVER_LOGIN_OK path, companion-v1.10.0+) with trailing server_timestamp
# (4B), acl_permissions (1B), fw_ver_level (1B).

@pytest.mark.asyncio
async def test_login_success_legacy_eight_byte_frame():
    """Legacy 8-byte LOGIN_SUCCESS: only permissions/is_admin/pubkey_prefix."""
    reader, dispatched = _make_reader()
    pubkey_prefix = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
    frame = bytes([PacketType.LOGIN_SUCCESS.value, 0x00]) + pubkey_prefix
    assert len(frame) == 8

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.LOGIN_SUCCESS
    assert evt.payload.get("permissions") == 0
    assert evt.payload.get("is_admin") is False
    assert evt.payload.get("pubkey_prefix") == pubkey_prefix.hex()
    assert "server_timestamp" not in evt.payload
    assert "acl_permissions" not in evt.payload
    assert "fw_ver_level" not in evt.payload


@pytest.mark.asyncio
async def test_login_success_modern_14_byte_frame():
    """Modern 14-byte LOGIN_SUCCESS (companion-v1.10.0+): all 6 keys."""
    reader, dispatched = _make_reader()
    pubkey_prefix = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
    server_timestamp = 0x12345678
    acl_permissions = 0x07
    fw_ver_level = 0x42
    frame = (
        bytes([PacketType.LOGIN_SUCCESS.value, 0x01])  # code + permissions (is_admin=True)
        + pubkey_prefix
        + server_timestamp.to_bytes(4, "little")
        + bytes([acl_permissions, fw_ver_level])
    )
    assert len(frame) == 14

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.LOGIN_SUCCESS
    assert evt.payload["permissions"] == 1
    assert evt.payload["is_admin"] is True
    assert evt.payload["pubkey_prefix"] == pubkey_prefix.hex()
    assert evt.payload["server_timestamp"] == server_timestamp
    assert evt.payload["acl_permissions"] == acl_permissions
    assert evt.payload["fw_ver_level"] == fw_ver_level


@pytest.mark.asyncio
async def test_login_success_intermediate_12_byte_frame():
    """Hypothetical 12-byte LOGIN_SUCCESS (server_timestamp only): per-field gates work."""
    reader, dispatched = _make_reader()
    pubkey_prefix = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
    server_timestamp = 0xDEADBEEF
    frame = (
        bytes([PacketType.LOGIN_SUCCESS.value, 0x00])
        + pubkey_prefix
        + server_timestamp.to_bytes(4, "little")
    )
    assert len(frame) == 12

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.payload["server_timestamp"] == server_timestamp
    assert "acl_permissions" not in evt.payload
    assert "fw_ver_level" not in evt.payload


# ---------------------------------------------------------------------------
# Wire-format parity bundle: ACK (trailing trip_time)
# ---------------------------------------------------------------------------
# Firmware emits 4-byte ack hash + 4-byte trip_time (ms) since companion-v1.0.0a
# (commit d9dc76f1, Jan 2025). The SDK had been silently dropping trip_time.

@pytest.mark.asyncio
async def test_ack_legacy_5_byte_frame():
    """Legacy 5-byte ACK frame (code + 4B hash): no trip_time."""
    reader, dispatched = _make_reader()
    ack_hash = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    frame = bytes([PacketType.ACK.value]) + ack_hash

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.ACK
    assert evt.payload.get("code") == ack_hash.hex()
    assert "trip_time" not in evt.payload


@pytest.mark.asyncio
async def test_ack_modern_9_byte_frame():
    """Modern 9-byte ACK frame (companion-v1.0.0a+): code + hash + trip_time."""
    reader, dispatched = _make_reader()
    ack_hash = bytes([0x01, 0x02, 0x03, 0x04])
    trip_time_ms = 1234
    frame = (
        bytes([PacketType.ACK.value])
        + ack_hash
        + trip_time_ms.to_bytes(4, "little")
    )

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.ACK
    assert evt.payload["code"] == ack_hash.hex()
    assert evt.payload["trip_time"] == trip_time_ms


# ---------------------------------------------------------------------------
# Wire-format parity bundle: RAW_DATA (reserved-byte cursor + variable payload)
# ---------------------------------------------------------------------------
# Firmware emits code(1) + snr(int8, ×4) + rssi(int8) + reserved(0xFF) + payload(N).
# Pre-fix SDK reads code+snr+rssi+payload(4B) -- swallowing the reserved byte
# as the first payload byte AND truncating to 4 bytes. Post-fix discards the
# reserved byte and reads the remainder.

@pytest.mark.asyncio
async def test_raw_data_realistic_frame():
    """RAW_DATA frame: dispatched payload matches firmware-emitted bytes exactly."""
    reader, dispatched = _make_reader()
    snr_quarters = -40  # -10.0 dB after / 4
    rssi = -75
    payload_bytes = bytes(range(0x10, 0x1A))  # 10 bytes of distinct data
    frame = (
        bytes([PacketType.RAW_DATA.value])
        + snr_quarters.to_bytes(1, "little", signed=True)
        + rssi.to_bytes(1, "little", signed=True)
        + bytes([0xFF])  # firmware reserved byte (intended as future path_len)
        + payload_bytes
    )

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.RAW_DATA
    # SNR/RSSI: keep the historical capitalised keys the SDK has always used.
    assert evt.payload["SNR"] == -10.0
    assert evt.payload["RSSI"] == rssi
    # Payload: full hex string of just the payload bytes (NO leading 0xff,
    # NO truncation to 4 bytes).
    assert evt.payload["payload"] == payload_bytes.hex()


# ---------------------------------------------------------------------------
# Wire-format parity bundle: DEFAULT_FLOOD_SCOPE (length-guarded read)
# ---------------------------------------------------------------------------
# Firmware emits a 48-byte frame when scope is set OR a 1-byte sentinel frame
# when no scope is configured. Pre-fix SDK over-reads 47 bytes on the sentinel
# and dispatches {scope_name: "", scope_key: ""}; post-fix dispatches {}.

@pytest.mark.asyncio
async def test_default_flood_scope_full_48_byte_frame():
    """48-byte DEFAULT_FLOOD_SCOPE: both scope_name and scope_key populated."""
    reader, dispatched = _make_reader()
    scope_name = b"my-scope" + b"\x00" * 23  # 31 bytes total, null-padded
    scope_key = bytes(range(16))
    frame = bytes([PacketType.DEFAULT_FLOOD_SCOPE.value]) + scope_name + scope_key
    assert len(frame) == 48

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.DEFAULT_FLOOD_SCOPE
    assert evt.payload["scope_name"] == "my-scope"
    assert evt.payload["scope_key"] == scope_key.hex()


@pytest.mark.asyncio
async def test_default_flood_scope_sentinel_frame_empty_payload():
    """1-byte sentinel DEFAULT_FLOOD_SCOPE frame: dispatched payload is empty dict."""
    reader, dispatched = _make_reader()
    frame = bytes([PacketType.DEFAULT_FLOOD_SCOPE.value])

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.DEFAULT_FLOOD_SCOPE
    # Post-fix: handler gates on len(data) >= 48, so the 1-byte sentinel
    # dispatches an empty payload (consumers detect "no scope" via key
    # presence, not via empty-string sentinel values).
    assert evt.payload == {}
