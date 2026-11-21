"""A telemetry response with a reading that can't be decoded keeps the readings before it (#119: A2)."""
import pytest

from meshcore.events import EventType
from meshcore.packets import BinaryReqType
from meshcore.reader import MessageReader

pytestmark = pytest.mark.asyncio

PUB6 = bytes(range(1, 7))
TEMPERATURE = bytes.fromhex("0167010e")  # channel 1, temperature, 27.0 C
UNKNOWN_TYPE = bytes.fromhex("02420102")  # channel 2, LPP type 0x42
CUT_SHORT = bytes.fromhex("0274")  # channel 2, voltage, no value


class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []

    async def dispatch(self, event):
        self.dispatched_events.append(event)


async def _telemetry_push(lpp):
    dispatcher = MockDispatcher()
    await MessageReader(dispatcher).handle_rx(bytearray(bytes([0x8B, 0x00]) + PUB6 + lpp))
    return [e for e in dispatcher.dispatched_events if e.type == EventType.TELEMETRY_RESPONSE]


@pytest.mark.parametrize("bad", [UNKNOWN_TYPE, CUT_SHORT], ids=["unknown_type", "cut_short"])
async def test_push_keeps_readings_before_an_undecodable_one(bad):
    events = await _telemetry_push(TEMPERATURE + bad)

    assert len(events) == 1
    payload = events[0].payload
    assert payload["lpp"] == [{"channel": 1, "type": "temperature", "value": 27.0}]
    assert payload["lpp_undecoded"] == bad.hex()


async def test_push_undecodable_first_reading():
    events = await _telemetry_push(UNKNOWN_TYPE)

    assert len(events) == 1
    assert events[0].payload["lpp"] == []
    assert events[0].payload["lpp_undecoded"] == UNKNOWN_TYPE.hex()


async def test_push_all_decoded_has_no_undecoded_field():
    events = await _telemetry_push(TEMPERATURE + b"\x00\x00")

    assert len(events) == 1
    assert events[0].payload["lpp"] == [{"channel": 1, "type": "temperature", "value": 27.0}]
    assert "lpp_undecoded" not in events[0].payload


async def test_binary_telemetry_response_keeps_readings_before_an_undecodable_one():
    dispatcher = MockDispatcher()
    reader = MessageReader(dispatcher)
    reader.register_binary_request("010203040506", "aabbccdd", BinaryReqType.TELEMETRY, 10.0)

    frame = bytes([0x8C, 0x00]) + bytes.fromhex("aabbccdd") + TEMPERATURE + UNKNOWN_TYPE
    await reader.handle_rx(bytearray(frame))

    events = [e for e in dispatcher.dispatched_events if e.type == EventType.TELEMETRY_RESPONSE]
    assert len(events) == 1
    assert events[0].payload["lpp"] == [{"channel": 1, "type": "temperature", "value": 27.0}]
    assert events[0].payload["lpp_undecoded"] == UNKNOWN_TYPE.hex()
    assert events[0].attributes["tag"] == "aabbccdd"


def test_lpp_parse_readings_reading_cut_inside_its_value():
    from meshcore.parsing import lpp_parse_readings

    readings, undecoded = lpp_parse_readings(TEMPERATURE + bytes.fromhex("026701"))

    assert readings == [{"channel": 1, "type": "temperature", "value": 27.0}]
    assert undecoded == bytes.fromhex("026701")
