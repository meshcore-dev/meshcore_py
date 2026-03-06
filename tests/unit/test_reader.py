#!/usr/bin/env python3

import asyncio
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
    from meshcore.parsing import BinaryReqType
    reader.register_binary_request(tag, BinaryReqType.ACL, 10.0)
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
        from meshcore.parsing import BinaryReqType
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

@pytest.mark.asyncio
async def test_device_info_v11_has_led_fields():
    """Firmware v11+ includes led_ble_mode and led_status_mode in DEVICE_INFO."""
    mock_dispatcher = MockDispatcher()
    reader = MessageReader(mock_dispatcher)

    # Build a DEVICE_INFO packet: PacketType.DEVICE_INFO (13) + fw_ver=11 + fields
    import struct
    packet = bytearray()
    packet.append(13)        # RESP_CODE_DEVICE_INFO
    packet.append(11)        # FIRMWARE_VER_CODE = 11
    packet.append(25)        # max_contacts / 2
    packet.append(8)         # max_channels
    packet += struct.pack("<I", 123456)  # ble_pin
    packet += b"20250305    "[:12]       # fw_build (12 bytes)
    packet += b"TestModel".ljust(40, b"\x00")  # model (40 bytes)
    packet += b"1.0.0".ljust(20, b"\x00")      # ver (20 bytes)
    packet.append(0)         # repeat (v9+)
    packet.append(1)         # path_hash_mode (v10+)
    packet.append(2)         # led_ble_mode (v11+) - LED_BLE_CONN_ONLY
    packet.append(1)         # led_status_mode (v11+) - LED_STATUS_DISABLED

    await reader.handle_rx(packet)

    device_events = [e for e in mock_dispatcher.dispatched_events if e.type == EventType.DEVICE_INFO]
    assert len(device_events) == 1
    info = device_events[0].payload
    assert info["fw ver"] == 11
    assert info["led_ble_mode"] == 2
    assert info["led_status_mode"] == 1


@pytest.mark.asyncio
async def test_device_info_v10_no_led_fields():
    """Firmware v10 should not have LED fields."""
    mock_dispatcher = MockDispatcher()
    reader = MessageReader(mock_dispatcher)

    import struct
    packet = bytearray()
    packet.append(13)        # RESP_CODE_DEVICE_INFO
    packet.append(10)        # FIRMWARE_VER_CODE = 10
    packet.append(25)        # max_contacts / 2
    packet.append(8)         # max_channels
    packet += struct.pack("<I", 0)       # ble_pin
    packet += b"20250101    "[:12]       # fw_build
    packet += b"OldModel".ljust(40, b"\x00")
    packet += b"0.9.0".ljust(20, b"\x00")
    packet.append(0)         # repeat (v9+)
    packet.append(0)         # path_hash_mode (v10+)

    await reader.handle_rx(packet)

    device_events = [e for e in mock_dispatcher.dispatched_events if e.type == EventType.DEVICE_INFO]
    assert len(device_events) == 1
    info = device_events[0].payload
    assert info["fw ver"] == 10
    assert "led_ble_mode" not in info
    assert "led_status_mode" not in info


if __name__ == "__main__":
    asyncio.run(test_binary_response())