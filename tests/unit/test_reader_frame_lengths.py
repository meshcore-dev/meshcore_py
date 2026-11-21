"""Frames cut short, or carrying a value the reader didn't expect (#119: A1, A3, A6)."""
import pytest

from meshcore.events import EventType
from meshcore.reader import MessageReader

pytestmark = pytest.mark.asyncio

PUB6 = bytes(range(1, 7))


class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []

    async def dispatch(self, event):
        self.dispatched_events.append(event)


async def _events(frame):
    dispatcher = MockDispatcher()
    await MessageReader(dispatcher).handle_rx(bytearray(frame))
    return dispatcher.dispatched_events


async def test_rx_log_transport_packet_cut_before_path_byte_is_dispatched():
    # LOG_DATA, SNR, RSSI, then a transport-flood packet: header 0x00 and
    # its 4-byte transport code, with no path byte after it.
    events = await _events(bytes([0x88, 0x10, 0xC4, 0x00, 1, 2, 3, 4]))

    assert [e.type for e in events] == [EventType.RX_LOG_DATA]
    payload = events[0].payload
    assert payload["payload"] == "0001020304"
    assert payload["route_typename"] == "UNK"
    assert payload["path"] == ""
    assert events[0].attributes["route_type"] == -1


async def test_rx_log_packet_cut_inside_its_path_is_not_given_a_short_path():
    # FLOOD packet (header 0x01) claiming 3 one-byte hops, with one present.
    events = await _events(bytes([0x88, 0x10, 0xC4, 0x01, 0x03, 0xAA]))

    assert [e.type for e in events] == [EventType.RX_LOG_DATA]
    assert events[0].payload["route_typename"] == "UNK"
    assert events[0].payload["path"] == ""


async def test_rx_log_whole_packet_still_parsed():
    # FLOOD packet, 2 one-byte hops, then a payload byte.
    events = await _events(bytes([0x88, 0x10, 0xC4, 0x01, 0x02, 0xAA, 0xBB, 0x99]))

    payload = events[0].payload
    assert payload["route_typename"] == "FLOOD"
    assert payload["path_len"] == 2
    assert payload["path"] == "aabb"
    assert payload["pkt_payload"] == b"\x99"


@pytest.mark.parametrize(
    "text, expected",
    [
        (b"gps", {}),
        (b"gps:1,", {"gps": "1"}),
        (b"gps:1,bat:2", {"gps": "1", "bat": "2"}),
        (b"url:http://x", {"url": "http://x"}),
    ],
)
async def test_custom_vars_pairs(text, expected):
    events = await _events(bytes([0x15]) + text)

    assert [e.type for e in events] == [EventType.CUSTOM_VARS]
    assert events[0].payload == expected


async def test_path_discovery_response_unknown_out_path():
    events = await _events(bytes([0x8D, 0x00]) + PUB6 + bytes([0xFF, 0x00]))

    assert [e.type for e in events] == [EventType.PATH_RESPONSE]
    payload = events[0].payload
    assert payload["out_path_len"] == -1
    assert payload["out_path"] == ""
    assert payload["in_path_len"] == 0
    assert payload["in_path"] == ""


async def test_path_discovery_response_cut_inside_a_path_is_not_dispatched():
    # no out path, then an in path of 2 one-byte hops with only one present
    events = await _events(bytes([0x8D, 0x00]) + PUB6 + bytes([0x00, 0x02, 0xAA]))

    assert not any(e.type == EventType.PATH_RESPONSE for e in events)


async def test_msg_sent_cut_short_is_an_error_not_a_message_sent():
    events = await _events(bytes([0x06, 0x00, 0xAA, 0xBB, 0xCC]))

    assert [e.type for e in events] == [EventType.ERROR]
    assert events[0].payload == {"reason": "invalid_frame_length"}


async def test_msg_sent_whole_frame():
    events = await _events(bytes([0x06, 0x01, 0xAA, 0xBB, 0xCC, 0xDD, 0x88, 0x13, 0x00, 0x00]))

    assert [e.type for e in events] == [EventType.MSG_SENT]
    assert events[0].payload == {
        "type": 1,
        "expected_ack": b"\xaa\xbb\xcc\xdd",
        "suggested_timeout": 5000,
    }
