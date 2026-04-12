#!/usr/bin/env python3

import asyncio
import logging
from unittest.mock import AsyncMock
from meshcore.events import EventType
from meshcore.reader import MessageReader

class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []
        
    async def dispatch(self, event):
        self.dispatched_events.append(event)
        print(f"Dispatched: {event.type} with payload keys: {list(event.payload.keys()) if hasattr(event.payload, 'keys') else event.payload}")

import pytest

@pytest.mark.asyncio
async def test_binary_response():
    mock_dispatcher = MockDispatcher()
    reader = MessageReader(mock_dispatcher)
    
    packet_hex = "8c00417db968993acd42fc77c3bbd1f08b9b84c39756410c58cd03077162bcb489031869586ab4b103000000000000000000"
    packet_data = bytearray.fromhex(packet_hex)
    
    print(f"Testing packet: {packet_hex}")
    print(f"Packet type: 0x{packet_data[0]:02x} (should be 0x8c for BINARY_RESPONSE)")
    
    # Register the binary request first
    tag = "417db968"
    from meshcore.packets import BinaryReqType
    pubkey_prefix = "993acd42fc77"
    reader.register_binary_request(pubkey_prefix, tag, BinaryReqType.ACL, 10.0)
    print(f"Registered ACL request with tag {tag}")
    
    await reader.handle_rx(packet_data)
    
    # Check what was dispatched
    print(f"\nTotal events dispatched: {len(mock_dispatcher.dispatched_events)}")
    
    # Verify BINARY_RESPONSE was dispatched
    binary_responses = [e for e in mock_dispatcher.dispatched_events if e.type == EventType.BINARY_RESPONSE]
    assert len(binary_responses) == 1, f"Expected 1 BINARY_RESPONSE, got {len(binary_responses)}"
    print("✅ BINARY_RESPONSE event dispatched correctly")
    
    # Check the binary response payload
    binary_event = binary_responses[0]
    assert "tag" in binary_event.payload, "BINARY_RESPONSE should have 'tag' in payload"
    assert "data" in binary_event.payload, "BINARY_RESPONSE should have 'data' in payload"
    print(f"✅ Binary response tag: {binary_event.payload['tag']}")
    print(f"✅ Binary response data: {binary_event.payload['data']}")
    
    # Check if a specific parsed event was also dispatched
    other_events = [e for e in mock_dispatcher.dispatched_events if e.type != EventType.BINARY_RESPONSE]
    if other_events:
        print(f"✅ Additional parsed event dispatched: {other_events[0].type}")
        print(f"   Payload keys: {list(other_events[0].payload.keys()) if hasattr(other_events[0].payload, 'keys') else other_events[0].payload}")
    else:
        print("⚠️ No additional parsed event dispatched")
    
    # Parse the response data to see what request type it is
    response_data = packet_data[6:]
    if response_data:
        request_type = response_data[0]
        print(f"Request type in response: 0x{request_type:02x} ({request_type})")
        
        # Map request types to expected events
        from meshcore.packets import BinaryReqType
        if request_type == BinaryReqType.STATUS.value:
            expected_event = EventType.STATUS_RESPONSE
        elif request_type == BinaryReqType.TELEMETRY.value:
            expected_event = EventType.TELEMETRY_RESPONSE
        elif request_type == BinaryReqType.MMA.value:
            expected_event = EventType.MMA_RESPONSE
        elif request_type == BinaryReqType.ACL.value:
            expected_event = EventType.ACL_RESPONSE
        else:
            expected_event = None
            
        if expected_event:
            specific_events = [e for e in mock_dispatcher.dispatched_events if e.type == expected_event]
            if specific_events:
                print(f"✅ Expected {expected_event} event was dispatched")
            else:
                print(f"❌ Expected {expected_event} event was NOT dispatched")
        else:
            print(f"⚠️ Unknown request type {request_type}, no specific event expected")

if __name__ == "__main__":
    asyncio.run(test_binary_response())


# ---------------------------------------------------------------------------
# G1 verification tests (proposal §4.1)
# ---------------------------------------------------------------------------

class _CapturingDispatcher:
    """Quiet dispatcher that records every dispatched event."""
    def __init__(self):
        self.events = []

    async def dispatch(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_g1_handle_rx_malformed_frame_logged_and_swallowed(caplog):
    """G1/F06: malformed frame must not propagate, must be logged with traceback."""
    dispatcher = _CapturingDispatcher()
    reader = MessageReader(dispatcher)

    # 4-byte CHANNEL_MSG_RECV_V3 frame: type byte (0x11) + 1 SNR byte +
    # 2 reserved bytes, but no channel_idx byte. The handler will raise
    # IndexError on the next dbuf.read(1)[0] when the buffer is empty.
    # F06's umbrella try/except must catch it, log the parse error, and
    # return cleanly.
    malformed = bytearray.fromhex("11100000")

    with caplog.at_level(logging.ERROR, logger="meshcore"):
        await reader.handle_rx(malformed)  # must not raise

    error_records = [r for r in caplog.records if "handle_rx parse error" in r.message]
    assert error_records, (
        f"Expected an error log containing 'handle_rx parse error'; "
        f"got: {[r.message for r in caplog.records]}"
    )
    # Traceback should be present in the log message (F06 includes it)
    assert "Traceback" in error_records[0].message, (
        "F06 umbrella log message must include a traceback"
    )
    # No CHANNEL_MSG_RECV event should have been dispatched
    assert not any(e.type == EventType.CHANNEL_MSG_RECV for e in dispatcher.events)


@pytest.mark.asyncio
async def test_g1_battery_short_frame_omits_storage_fields():
    """G1/N07: short BATTERY frame must not silently yield zero used_kb/total_kb."""
    dispatcher = _CapturingDispatcher()
    reader = MessageReader(dispatcher)

    # 3-byte BATTERY frame: type 0x0c + 2 level bytes (no storage tail).
    # Pre-fix the `len(data) > 3` gate would have let any frame >= 4 bytes
    # through, producing a BATTERY event with bogus zero used_kb/total_kb
    # because io.BytesIO.read() returns short data without raising.
    # Post-fix (`len(data) >= 11`) the storage fields are skipped entirely.
    short_battery = bytearray.fromhex("0c8000")

    await reader.handle_rx(short_battery)

    battery_events = [e for e in dispatcher.events if e.type == EventType.BATTERY]
    assert len(battery_events) == 1, (
        f"Expected exactly one BATTERY event, got {len(battery_events)}"
    )
    payload = battery_events[0].payload
    assert payload["level"] == 0x0080, f"Unexpected level: {payload['level']}"
    assert "used_kb" not in payload, (
        "Short BATTERY frame must not include used_kb (would be a silent zero)"
    )
    assert "total_kb" not in payload, (
        "Short BATTERY frame must not include total_kb (would be a silent zero)"
    )


@pytest.mark.asyncio
async def test_g1_status_response_short_frame_skipped(caplog):
    """G1/NEW-C: short STATUS_RESPONSE push frame must be skipped, not parsed with bogus zeros."""
    dispatcher = _CapturingDispatcher()
    reader = MessageReader(dispatcher)

    # 30-byte STATUS_RESPONSE push frame, well below the 60-byte minimum.
    # First byte is the type (0x87 = PacketType.STATUS_RESPONSE), the rest
    # is arbitrary filler. parse_status with offset=8 reads up through
    # data[56:60], so anything < 60 bytes would yield short reads and
    # silent zero values pre-fix.
    short_status = bytearray([0x87] + [0xAA] * 29)
    assert len(short_status) == 30

    with caplog.at_level(logging.DEBUG, logger="meshcore"):
        await reader.handle_rx(short_status)

    status_events = [e for e in dispatcher.events if e.type == EventType.STATUS_RESPONSE]
    assert len(status_events) == 0, (
        "Short STATUS_RESPONSE push frame must not dispatch a parsed event"
    )
    assert any(
        "STATUS_RESPONSE push frame too short" in r.message for r in caplog.records
    ), "Expected the NEW-C debug log line for short STATUS_RESPONSE frames"


@pytest.mark.asyncio
async def test_g1_parse_packet_payload_txt_type_decodes_high_bits():
    """G1/R02: txt_type must decode the high 6 bits of byte 4, not always be 0."""
    from Crypto.Cipher import AES
    from Crypto.Hash import HMAC, SHA256
    from meshcore.meshcore_parser import MeshcorePacketParser

    parser = MeshcorePacketParser()
    parser.decrypt_channels = True

    # Set up a synthetic channel with a known 16-byte AES key. Direct dict
    # assignment matches how the parser stores channels (newChannel is async
    # and serves the same purpose).
    channel_secret = b"\x01" * 16
    channel_hash_byte = 0xAB
    parser.channels[0] = {
        "channel_idx": 0,
        "channel_name": "test",
        "channel_hash": "ab",
        "channel_secret": channel_secret,
    }

    # 16-byte plaintext (one AES block):
    #   bytes 0-3 = sender_timestamp (little-endian)
    #   byte 4    = (txt_type << 2) | attempt
    #   bytes 5-15 = message + null padding
    # Pick txt_type=5, attempt=1 → byte 4 = (5 << 2) | 1 = 0x15.
    # Pre-R02-fix uncrypted[4:4] is empty so txt_type would be 0;
    # post-fix uncrypted[4:5] yields 0x15 >> 2 = 5.
    plaintext = b"\x00\x00\x00\x00\x15hello\x00\x00\x00\x00\x00\x00"
    assert len(plaintext) == 16

    encrypted = AES.new(channel_secret, AES.MODE_ECB).encrypt(plaintext)

    # cipher_mac = first 2 bytes of HMAC-SHA256(channel_secret, encrypted)
    h = HMAC.new(channel_secret, digestmod=SHA256)
    h.update(encrypted)
    cipher_mac = h.digest()[:2]

    # pkt_payload layout: 1-byte chan_hash + 2-byte cipher_mac + ciphertext
    pkt_payload = bytes([channel_hash_byte]) + cipher_mac + encrypted

    # parsePacketPayload expects the full payload buffer:
    #   header byte (route_type=1 DIRECT, payload_type=5 channel, ver=0)
    #   path_byte  (path_len=0, path_hash_size=1) → 0x00
    #   pkt_payload
    header = 0x15  # route_type=1, payload_type=5, payload_ver=0
    path_byte = 0x00
    payload = bytes([header, path_byte]) + pkt_payload

    log_data = await parser.parsePacketPayload(payload, log_data={})

    assert log_data["payload_type"] == 0x05
    assert "txt_type" in log_data, (
        f"txt_type missing from log_data — channel decrypt path was not reached. "
        f"log_data keys: {list(log_data.keys())}"
    )
    assert log_data["txt_type"] == 5, (
        f"Expected txt_type=5 (R02 fix), got {log_data['txt_type']}"
    )
    assert log_data["attempt"] == 1, (
        f"Expected attempt=1, got {log_data['attempt']}"
    )