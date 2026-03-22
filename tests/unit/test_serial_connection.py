import asyncio

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
