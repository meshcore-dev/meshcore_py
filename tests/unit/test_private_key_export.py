#!/usr/bin/env python3
"""
Unit tests for private key export functionality
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from meshcore.commands import CommandHandler
from meshcore.events import Event, EventType, Subscription
from meshcore.reader import MessageReader

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_connection():
    connection = MagicMock()
    connection.send = AsyncMock()
    return connection


@pytest.fixture
def mock_dispatcher():
    dispatcher = MagicMock()
    dispatcher.wait_for_event = AsyncMock()
    dispatcher.dispatch = AsyncMock()

    def fake_subscribe(event_type, handler, attribute_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        return sub

    dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)
    return dispatcher


@pytest.fixture
def command_handler(mock_connection, mock_dispatcher):
    handler = CommandHandler()

    async def sender(data):
        await mock_connection.send(data)

    handler._sender_func = sender
    handler.dispatcher = mock_dispatcher
    return handler


def setup_event_response(mock_dispatcher, event_type, payload):
    def fake_subscribe(evt_type, handler, attr_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        if evt_type == event_type:
            asyncio.get_event_loop().call_soon(
                handler, Event(event_type, payload)
            )
        return sub

    mock_dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)


# Command tests
async def test_export_private_key_success(command_handler, mock_connection, mock_dispatcher):
    """Test successful private key export"""
    private_key_data = b"x" * 64
    expected_payload = {"private_key": private_key_data}
    setup_event_response(mock_dispatcher, EventType.PRIVATE_KEY, expected_payload)

    result = await command_handler.export_private_key()

    # Verify the command was sent correctly
    mock_connection.send.assert_called_once_with(b"\x17")
    assert result.type == EventType.PRIVATE_KEY
    assert len(result.payload["private_key"]) == 64
    assert result.payload["private_key"] == private_key_data


async def test_export_private_key_disabled(command_handler, mock_connection, mock_dispatcher):
    """Test private key export when disabled"""
    expected_payload = {"reason": "private_key_export_disabled"}
    setup_event_response(mock_dispatcher, EventType.DISABLED, expected_payload)

    result = await command_handler.export_private_key()

    # Verify the command was sent correctly
    mock_connection.send.assert_called_once_with(b"\x17")
    assert result.type == EventType.DISABLED
    assert result.payload["reason"] == "private_key_export_disabled"


async def test_export_private_key_error(command_handler, mock_connection, mock_dispatcher):
    """Test private key export error handling"""
    expected_payload = {"reason": "timeout"}
    setup_event_response(mock_dispatcher, EventType.ERROR, expected_payload)

    result = await command_handler.export_private_key()

    # Verify the command was sent correctly
    mock_connection.send.assert_called_once_with(b"\x17")
    assert result.type == EventType.ERROR
    assert result.payload["reason"] == "timeout"


# Packet parsing tests
class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []
        
    async def dispatch(self, event):
        self.dispatched_events.append(event)


async def test_parse_private_key_packet():
    """Test parsing of PRIVATE_KEY packet (type 14)"""
    mock_dispatcher = MockDispatcher()
    reader = MessageReader(mock_dispatcher)
    
    # Create a mock private key packet: [14][64 bytes of key data]
    private_key_data = b"x" * 64
    packet = bytes([14]) + private_key_data  # PRIVATE_KEY = 14
    
    await reader.handle_rx(bytearray(packet))
    
    # Verify the event was dispatched
    assert len(mock_dispatcher.dispatched_events) == 1
    event = mock_dispatcher.dispatched_events[0]
    
    assert event.type == EventType.PRIVATE_KEY
    assert event.payload["private_key"] == private_key_data


async def test_parse_private_key_packet_invalid_length():
    """Test parsing of PRIVATE_KEY packet with invalid length"""
    mock_dispatcher = MockDispatcher()
    reader = MessageReader(mock_dispatcher)
    
    # Create a packet that's too short
    packet = bytes([14]) + b"short"  # Only 5 bytes instead of 64
    
    await reader.handle_rx(bytearray(packet))
    
    # Should not dispatch an event for invalid length
    assert len(mock_dispatcher.dispatched_events) == 0


async def test_parse_disabled_packet():
    """Test parsing of DISABLED packet (type 15)"""
    mock_dispatcher = MockDispatcher()
    reader = MessageReader(mock_dispatcher)
    
    # Create a disabled packet: [15]
    packet = bytes([15])  # DISABLED = 15
    
    await reader.handle_rx(bytearray(packet))
    
    # Verify the event was dispatched
    assert len(mock_dispatcher.dispatched_events) == 1
    event = mock_dispatcher.dispatched_events[0]
    
    assert event.type == EventType.DISABLED
    assert event.payload["reason"] == "private_key_export_disabled"
