"""
Regression test for GH #97: after a BLE reconnect, the previous client's GATT
notification subscription was never torn down, so every notification fired
twice (once for the stale registration, once for the new one).

connect() must disconnect any existing self.client before overwriting it with
a fresh BleakClient.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from meshcore.ble_cx import BLEConnection, UART_RX_CHAR_UUID


class _FakeBleakClient:
    """Stand-in for BleakClient whose constructor hands out pre-built
    instances, so tests can assert on a specific client object while
    connect()'s `isinstance(self.client, BleakClient)` check still holds."""

    _queue = []

    def __new__(cls, *args, **kwargs):
        return cls._queue.pop(0)


def _make_mock_client(address):
    """Build a mock client instance (bypassing __new__'s queue pop)."""
    client = object.__new__(_FakeBleakClient)
    client.address = address
    client.is_connected = True
    client.connect = AsyncMock()
    client.start_notify = AsyncMock()

    async def _disconnect():
        # Mirrors real BleakClient: once disconnected, is_connected flips.
        client.is_connected = False

    client.disconnect = AsyncMock(side_effect=_disconnect)

    mock_service = MagicMock()
    mock_char = MagicMock()
    mock_char.uuid = UART_RX_CHAR_UUID
    mock_service.get_characteristic.return_value = mock_char
    client.services = MagicMock()
    client.services.get_service.return_value = mock_service

    return client


@pytest.mark.asyncio
async def test_reconnect_disconnects_previous_client_before_replacing_it():
    """Calling connect() twice in a row (as happens on a BLE reconnect) must
    disconnect the first client before the second one is constructed, so its
    stale notify registration doesn't linger alongside the new one."""
    address = "00:11:22:33:44:55"
    first_client = _make_mock_client(address)
    second_client = _make_mock_client(address)
    _FakeBleakClient._queue = [first_client, second_client]

    with patch("meshcore.ble_cx.BleakClient", _FakeBleakClient):
        ble_conn = BLEConnection(address=address)

        result = await ble_conn.connect()
        assert result == address
        assert ble_conn.client is first_client
        first_client.disconnect.assert_not_awaited()

        result = await ble_conn.connect()
        assert result == address
        assert ble_conn.client is second_client

        # The stale first client must be disconnected before the second
        # client is used, so its GATT notify subscription doesn't survive
        # alongside the new one.
        first_client.disconnect.assert_awaited_once()
        second_client.start_notify.assert_awaited_once()

        assert _FakeBleakClient._queue == []
