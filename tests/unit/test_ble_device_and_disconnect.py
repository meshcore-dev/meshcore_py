"""Connecting to a passed BLE device, and closing a link not marked connected (#119: C1, C2)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from meshcore.ble_cx import UART_RX_CHAR_UUID, BLEConnection
from meshcore.connection_manager import ConnectionManager
from meshcore.events import EventType

pytestmark = pytest.mark.asyncio

ADDRESS = "00:11:22:33:44:55"


class _FakeBleakClient:
    """Stand-in for BleakClient that hands out a pre-built instance, so
    connect()'s isinstance check still holds."""

    _queue = []

    def __new__(cls, *args, **kwargs):
        return cls._queue.pop(0)


def _make_mock_client(address):
    client = object.__new__(_FakeBleakClient)
    client.address = address
    client.is_connected = False
    client.connect = AsyncMock()
    client.start_notify = AsyncMock()
    client.disconnect = AsyncMock()
    service = MagicMock()
    char = MagicMock()
    char.uuid = UART_RX_CHAR_UUID
    service.get_characteristic.return_value = char
    client.services = MagicMock()
    client.services.get_service.return_value = service
    return client


async def test_connect_to_a_passed_device_returns_its_address():
    device = MagicMock()
    device.address = ADDRESS
    _FakeBleakClient._queue = [_make_mock_client(ADDRESS)]

    with patch("meshcore.ble_cx.BleakClient", _FakeBleakClient):
        result = await BLEConnection(device=device).connect()

    assert result == ADDRESS


class RecordingConnection:
    def __init__(self, connect_result):
        self.connect_result = connect_result
        self.disconnects = 0

    async def connect(self):
        return self.connect_result

    async def disconnect(self):
        self.disconnects += 1

    async def send(self, data):
        pass

    def set_reader(self, reader):
        pass


class RecordingDispatcher:
    def __init__(self):
        self.events = []

    async def dispatch(self, event):
        self.events.append(event)


def _manager(connection):
    dispatcher = RecordingDispatcher()
    return ConnectionManager(connection, dispatcher), dispatcher


def _disconnected(dispatcher):
    return [e.payload["reason"] for e in dispatcher.events if e.type == EventType.DISCONNECTED]


async def test_disconnect_closes_a_link_whose_connect_returned_none():
    connection = RecordingConnection(connect_result=None)
    manager, dispatcher = _manager(connection)

    await manager.connect()
    await manager.disconnect()

    assert connection.disconnects == 1
    assert _disconnected(dispatcher) == []  # it was never reported connected


async def test_disconnect_closes_a_link_marked_lost():
    connection = RecordingConnection(connect_result="ok")
    manager, dispatcher = _manager(connection)

    await manager.connect()
    await manager.handle_disconnect("ble_write_failed")
    await manager.disconnect()

    assert connection.disconnects == 1
    assert _disconnected(dispatcher) == ["ble_write_failed"]


async def test_disconnect_of_a_connected_link_is_reported_once():
    connection = RecordingConnection(connect_result="ok")
    manager, dispatcher = _manager(connection)

    await manager.connect()
    await manager.disconnect()

    assert connection.disconnects == 1
    assert _disconnected(dispatcher) == ["manual_disconnect"]
