"""Tests for meshcore.parsing.parse_status covering the RepeaterStats binary frame.

The firmware struct (MeshCore/examples/simple_repeater/MyMesh.h) is:

    struct RepeaterStats {
      uint16_t batt_milli_volts;        // offset  0 (2)
      uint16_t curr_tx_queue_len;       // offset  2 (2)
      int16_t  noise_floor;             // offset  4 (2)
      int16_t  last_rssi;               // offset  6 (2)
      uint32_t n_packets_recv;          // offset  8 (4)
      uint32_t n_packets_sent;          // offset 12 (4)
      uint32_t total_air_time_secs;     // offset 16 (4)
      uint32_t total_up_time_secs;      // offset 20 (4)
      uint32_t n_sent_flood;            // offset 24 (4)
      uint32_t n_sent_direct;           // offset 28 (4)
      uint32_t n_recv_flood;            // offset 32 (4)
      uint32_t n_recv_direct;           // offset 36 (4)
      uint16_t err_events;              // offset 40 (2)
      int16_t  last_snr;   // x4        // offset 42 (2)
      uint16_t n_direct_dups;           // offset 44 (2)
      uint16_t n_flood_dups;            // offset 46 (2)
      uint32_t total_rx_air_time_secs;  // offset 48 (4)
      uint32_t n_recv_errors;           // offset 52 (4)  -- 56-byte frame
    };
"""
import struct
from meshcore.parsing import parse_status


def _build_frame(
    *,
    bat=4200,
    tx_queue_len=3,
    noise_floor=-118,
    last_rssi=-85,
    nb_recv=1000,
    nb_sent=500,
    airtime=3600,
    uptime=86400,
    sent_flood=100,
    sent_direct=400,
    recv_flood=300,
    recv_direct=700,
    err_events=0,
    last_snr_x4=30,  # 7.5 dB * 4
    direct_dups=5,
    flood_dups=10,
    rx_airtime=7200,
    recv_errors=None,
):
    """Build a RepeaterStats binary frame (52 or 56 bytes)."""
    frame = struct.pack(
        "<HHhhIIIIIIIIHhHHI",
        bat,
        tx_queue_len,
        noise_floor,
        last_rssi,
        nb_recv,
        nb_sent,
        airtime,
        uptime,
        sent_flood,
        sent_direct,
        recv_flood,
        recv_direct,
        err_events,
        last_snr_x4,
        direct_dups,
        flood_dups,
        rx_airtime,
    )
    assert len(frame) == 52
    if recv_errors is not None:
        frame += struct.pack("<I", recv_errors)
    return frame


class TestParseStatusWithPrefix:
    """parse_status called with an explicit pubkey_prefix (binary-request path)."""

    def test_full_56_byte_frame(self):
        data = _build_frame(recv_errors=42)
        res = parse_status(data, pubkey_prefix="aabb11223344")

        assert res["pubkey_pre"] == "aabb11223344"
        assert res["bat"] == 4200
        assert res["tx_queue_len"] == 3
        assert res["noise_floor"] == -118
        assert res["last_rssi"] == -85
        assert res["nb_recv"] == 1000
        assert res["nb_sent"] == 500
        assert res["airtime"] == 3600
        assert res["uptime"] == 86400
        assert res["sent_flood"] == 100
        assert res["sent_direct"] == 400
        assert res["recv_flood"] == 300
        assert res["recv_direct"] == 700
        assert res["full_evts"] == 0
        assert res["last_snr"] == 7.5
        assert res["direct_dups"] == 5
        assert res["flood_dups"] == 10
        assert res["rx_airtime"] == 7200
        assert res["recv_errors"] == 42

    def test_legacy_52_byte_frame(self):
        data = _build_frame()  # no recv_errors → 52 bytes
        res = parse_status(data, pubkey_prefix="aabb11223344")

        assert res["bat"] == 4200
        assert res["recv_errors"] is None

    def test_nonzero_recv_errors(self):
        data = _build_frame(recv_errors=123456)
        res = parse_status(data, pubkey_prefix="cc1122334455")
        assert res["recv_errors"] == 123456


class TestParseStatusEmbedded:
    """parse_status called without pubkey_prefix (STATUS_RESPONSE push path).

    In this path the first 2 bytes are a header, bytes 2-8 are the pubkey
    prefix, and fields start at offset 8.
    """

    def test_56_byte_payload_with_header(self):
        header = b"\x00\x00"  # 2-byte header
        pubkey = bytes.fromhex("aabb11223344")  # 6-byte prefix
        body = _build_frame(recv_errors=99)
        data = header + pubkey + body

        res = parse_status(data)

        assert res["pubkey_pre"] == "aabb11223344"
        assert res["bat"] == 4200
        assert res["recv_errors"] == 99

    def test_52_byte_payload_with_header(self):
        header = b"\x00\x00"
        pubkey = bytes.fromhex("aabb11223344")
        body = _build_frame()  # 52 bytes, no recv_errors
        data = header + pubkey + body

        res = parse_status(data)

        assert res["pubkey_pre"] == "aabb11223344"
        assert res["recv_errors"] is None
