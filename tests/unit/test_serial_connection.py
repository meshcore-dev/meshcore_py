import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from meshcore.serial_cx import SerialConnection


class RecordingReader:
    def __init__(self):
        self.frames = []

    async def handle_rx(self, data):
        self.frames.append(bytes(data))


@pytest.mark.asyncio
async def test_handle_rx_discards_leading_junk_before_frame_start():
    conn = SerialConnection("/dev/null", 115200)
    reader = RecordingReader()
    conn.set_reader(reader)

    payload = b"\x00\x01\x02\x53"
    frame = b"\x3e" + len(payload).to_bytes(2, "little") + payload

    conn.handle_rx(b"junk bytes\r\n" + frame)
    await asyncio.sleep(0)

    assert reader.frames == [payload]
    assert conn.header == b""
    assert conn.inframe == b""
    assert conn.frame_expected_size == 0


@pytest.mark.asyncio
async def test_connect_closes_transport_on_timeout():
    """Regression for #95: if connection_made() never fires before the
    connect() timeout, the fds create_serial_connection() already opened
    must not leak -- connect() should close the transport before raising."""
    conn = SerialConnection("/dev/null", 115200)

    mock_transport = MagicMock()
    mock_protocol = MagicMock()

    async def fake_create_serial_connection(loop, protocol_factory, port, baudrate):
        # Never call connection_made(), so _connected_event stays unset.
        return mock_transport, mock_protocol

    with patch(
        "meshcore.serial_cx.serial_asyncio.create_serial_connection",
        side_effect=fake_create_serial_connection,
    ):
        with pytest.raises(asyncio.TimeoutError):
            await conn.connect(timeout=0.05)

    mock_transport.close.assert_called_once()
    assert conn.transport is None
