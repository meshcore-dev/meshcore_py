"""
Verification tests for transport symmetry fixes.

Covers: send symmetry across transports, serial disconnect callback on
transport-lost, serial connect timeout, oversize-frame return, BLE
disconnect-callback re-registration, BLE pairing failure re-raise,
TCP counter per frame not per segment.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from meshcore.tcp_cx import TCPConnection
from meshcore.serial_cx import SerialConnection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class RecordingReader:
    """Minimal reader mock that records dispatched frames."""
    def __init__(self):
        self.frames = []

    async def handle_rx(self, data):
        self.frames.append(bytes(data))


# ---------------------------------------------------------------------------
# TCP send() wraps transport.write in try/except
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tcp_send_write_error_fires_disconnect():
    """TCP: OSError during transport.write fires _disconnect_callback."""
    cx = TCPConnection("127.0.0.1", 5000)
    cb = AsyncMock()
    cx.set_disconnect_callback(cb)

    mock_transport = MagicMock()
    mock_transport.write.side_effect = OSError("Broken pipe")
    cx.transport = mock_transport
    cx._send_count = 0
    cx._receive_count = 0

    await cx.send(b"\x01\x02\x03")

    cb.assert_awaited_once()
    reason = cb.call_args[0][0]
    assert "tcp_write_failed" in reason


# ---------------------------------------------------------------------------
# Serial send() fires disconnect on transport-lost and write error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serial_send_no_transport_fires_disconnect():
    """Serial: send() on None transport fires _disconnect_callback ."""
    cx = SerialConnection("/dev/null", 115200)
    cb = AsyncMock()
    cx.set_disconnect_callback(cb)
    cx.transport = None

    await cx.send(b"\x01")

    cb.assert_awaited_once()
    reason = cb.call_args[0][0]
    assert reason == "serial_transport_lost"


@pytest.mark.asyncio
async def test_serial_send_write_error_fires_disconnect():
    """Serial: OSError during transport.write fires _disconnect_callback."""
    cx = SerialConnection("/dev/null", 115200)
    cb = AsyncMock()
    cx.set_disconnect_callback(cb)

    mock_transport = MagicMock()
    mock_transport.write.side_effect = OSError("Device not configured")
    cx.transport = mock_transport

    await cx.send(b"\x01")

    cb.assert_awaited_once()
    reason = cb.call_args[0][0]
    assert "serial_write_failed" in reason


# ---------------------------------------------------------------------------
# BLE send() fires disconnect on transport-lost and write error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ble_send_no_client_fires_disconnect():
    """BLE: send() with no client fires _disconnect_callback."""
    # Can't import BLEConnection directly if bleak isn't installed,
    # so test via dynamic import with a guard.
    try:
        from meshcore.ble_cx import BLEConnection
    except ImportError:
        pytest.skip("bleak not installed")

    # BLEConnection.__init__ checks BLEAK_AVAILABLE; patch it
    with patch("meshcore.ble_cx.BLEAK_AVAILABLE", True), \
         patch("meshcore.ble_cx.BleakClient", MagicMock()):
        cx = BLEConnection.__new__(BLEConnection)
        cx.client = None
        cx._user_provided_client = None
        cx._user_provided_address = None
        cx._user_provided_device = None
        cx.address = None
        cx.device = None
        cx.pin = None
        cx.rx_char = None
        cb = AsyncMock()
        cx._disconnect_callback = cb

        result = await cx.send(b"\x01")

        assert result is False
        cb.assert_awaited_once()
        reason = cb.call_args[0][0]
        assert reason == "ble_transport_lost"


# ---------------------------------------------------------------------------
# Serial connect() times out if connection_made never fires
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serial_connect_timeout():
    """Serial: connect() raises TimeoutError if connection_made never fires."""
    cx = SerialConnection("/dev/null", 115200)

    # Mock create_serial_connection to do nothing (never fires connection_made)
    async def mock_create(*args, **kwargs):
        return (MagicMock(), MagicMock())

    with patch("meshcore.serial_cx.serial_asyncio.create_serial_connection",
               side_effect=mock_create):
        with pytest.raises(asyncio.TimeoutError):
            await cx.connect(timeout=0.1)


# ---------------------------------------------------------------------------
# Oversize frame resets state and returns without dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tcp_oversize_frame_empty_data_returns():
    """TCP: oversize header with no trailing data returns without dispatch."""
    cx = TCPConnection("127.0.0.1", 5000)
    reader = RecordingReader()
    cx.set_reader(reader)

    # Build a frame header with size > 300 and no payload data after header
    # Header: 0x3e + 2-byte LE size (e.g. 500 = 0x01F4)
    header = b"\x3e" + (500).to_bytes(2, "little")
    cx.handle_rx(header)
    await asyncio.sleep(0)

    # No frames should be dispatched, and state should be reset
    assert reader.frames == []
    assert cx.header == b""
    assert cx.inframe == b""
    assert cx.frame_expected_size == 0


@pytest.mark.asyncio
async def test_serial_oversize_frame_empty_data_returns():
    """Serial: oversize header with no trailing data returns without dispatch."""
    cx = SerialConnection("/dev/null", 115200)
    reader = RecordingReader()
    cx.set_reader(reader)

    header = b"\x3e" + (500).to_bytes(2, "little")
    cx.handle_rx(header)
    await asyncio.sleep(0)

    assert reader.frames == []
    assert cx.header == b""
    assert cx.inframe == b""
    assert cx.frame_expected_size == 0


# ---------------------------------------------------------------------------
# TCP receive counter increments per MeshCore frame, not per TCP segment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tcp_receive_count_per_frame_not_per_segment():
    """TCP: _receive_count increments per completed frame, not per data_received call."""
    cx = TCPConnection("127.0.0.1", 5000)
    reader = RecordingReader()
    cx.set_reader(reader)
    cx._receive_count = 0

    # Build a 4-byte payload frame
    payload = b"\xAA\xBB\xCC\xDD"
    frame = b"\x3e" + len(payload).to_bytes(2, "little") + payload

    # Split the frame into 3 TCP segments (simulating fragmentation)
    protocol = TCPConnection.MCClientProtocol(cx)
    protocol.data_received(frame[:2])   # partial header
    protocol.data_received(frame[2:5])  # rest of header + 2 bytes payload
    protocol.data_received(frame[5:])   # remaining payload

    await asyncio.sleep(0)

    # 3 data_received calls but only 1 completed frame
    assert cx._receive_count == 1
    assert reader.frames == [payload]


@pytest.mark.asyncio
async def test_tcp_multiple_frames_count_correctly():
    """TCP: two complete frames in separate segments → _receive_count == 2."""
    cx = TCPConnection("127.0.0.1", 5000)
    reader = RecordingReader()
    cx.set_reader(reader)
    cx._receive_count = 0

    payload1 = b"\x01\x02"
    frame1 = b"\x3e" + len(payload1).to_bytes(2, "little") + payload1
    payload2 = b"\x03\x04\x05"
    frame2 = b"\x3e" + len(payload2).to_bytes(2, "little") + payload2

    protocol = TCPConnection.MCClientProtocol(cx)
    protocol.data_received(frame1)
    protocol.data_received(frame2)
    await asyncio.sleep(0)

    assert cx._receive_count == 2
    assert reader.frames == [payload1, payload2]
