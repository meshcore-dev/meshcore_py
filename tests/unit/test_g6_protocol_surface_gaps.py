"""Verification tests for G6 — Protocol surface gaps (N01, N02, N03, N05, N09, R04).

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
# N01 — CONTACT_DELETED handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contact_deleted_dispatches_event():
    """N01: A 33-byte CONTACT_DELETED frame dispatches EventType.CONTACT_DELETED."""
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
    """N01: A CONTACT_DELETED frame shorter than 33 bytes is silently dropped."""
    reader, dispatched = _make_reader()
    # Only 10 bytes — too short
    frame = bytes([PacketType.CONTACT_DELETED.value]) + b"\x00" * 9

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 0


# ---------------------------------------------------------------------------
# N02 — CONTACTS_FULL handler + enum entry
# ---------------------------------------------------------------------------

def test_contacts_full_enum_exists():
    """N02: PacketType.CONTACTS_FULL == 0x90."""
    assert PacketType.CONTACTS_FULL.value == 0x90


@pytest.mark.asyncio
async def test_contacts_full_dispatches_event():
    """N02: A 1-byte CONTACTS_FULL push dispatches EventType.CONTACTS_FULL."""
    reader, dispatched = _make_reader()
    frame = bytes([PacketType.CONTACTS_FULL.value])

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.CONTACTS_FULL
    assert evt.payload == {}


# ---------------------------------------------------------------------------
# N03 — TUNING_PARAMS handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tuning_params_dispatches_event():
    """N03: A 9-byte TUNING_PARAMS frame dispatches with rx_delay and airtime_factor."""
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
    """N03: A TUNING_PARAMS frame shorter than 9 bytes dispatches ERROR."""
    reader, dispatched = _make_reader()
    # Only 5 bytes — too short
    frame = bytes([PacketType.TUNING_PARAMS.value]) + b"\x01\x00\x00\x00"

    await reader.handle_rx(bytearray(frame))

    assert len(dispatched) == 1
    evt = dispatched[0]
    assert evt.type == EventType.ERROR
    assert evt.payload["reason"] == "invalid_frame_length"


# ---------------------------------------------------------------------------
# N05 — send_trace() one-byte pad
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_trace_empty_path_pads_to_11_bytes():
    """N05: send_trace() with no path produces an 11-byte packet (not 10)."""
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
    """N05: send_trace() with a non-empty path does NOT add padding."""
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
# N09 — Command wrapper: send_raw_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_raw_data_wrapper():
    """N09: send_raw_data sends CMD 0x19 + payload."""
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
# N09 — Command wrapper: has_connection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_has_connection_wrapper():
    """N09: has_connection sends CMD 0x1c."""
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
# N09 — Command wrapper: get_tuning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tuning_wrapper():
    """N09/N03: get_tuning sends CMD 0x2b (GET_TUNING_PARAMS = 43)."""
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
# N09 — Command wrapper: get_contact_by_key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_contact_by_key_wrapper():
    """N09: get_contact_by_key sends CMD 0x1e + 32-byte pubkey."""
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
# N09 — Command wrapper: factory_reset (two-step)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_factory_reset_two_step():
    """N09: factory_reset requires a token from request_factory_reset."""
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
    """N09: confirm_factory_reset without request_factory_reset raises ValueError."""
    from meshcore.commands.device import DeviceCommands

    cmd = DeviceCommands.__new__(DeviceCommands)

    with pytest.raises(ValueError, match="Invalid or expired"):
        await cmd.confirm_factory_reset("any_token")


# ---------------------------------------------------------------------------
# R04 — GET_STATS enum entry
# ---------------------------------------------------------------------------

def test_get_stats_enum_exists():
    """R04: CommandType.GET_STATS == 56."""
    assert CommandType.GET_STATS.value == 56


@pytest.mark.asyncio
async def test_get_stats_core_uses_enum():
    """R04: get_stats_core sends CommandType.GET_STATS.value (0x38) + 0x00."""
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
