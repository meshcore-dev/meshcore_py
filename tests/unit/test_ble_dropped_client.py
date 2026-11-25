"""A BLE client whose link dropped is disconnected, so bleak releases its D-Bus connection (#135)."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from meshcore.ble_cx import BLEConnection
from meshcore.connection_manager import ConnectionManager

pytestmark = pytest.mark.asyncio

ADDRESS = "AA:BB:CC:DD:EE:FF"


class StubClient:
    """Stands in for a BleakClient, counting its disconnect() calls."""

    def __init__(self, address, disconnected_callback=None):
        self.address = address
        self.is_connected = False
        self.disconnected_callback = disconnected_callback
        self.disconnect_calls = 0
        self.services = MagicMock()

    async def connect(self):
        self.is_connected = True

    async def start_notify(self, uuid, callback):
        pass

    async def disconnect(self):
        # As bleak does: the callback runs only for a link that was up, and a
        # second call does nothing to the device.
        self.disconnect_calls += 1
        if self.is_connected:
            self.drop()

    def drop(self):
        """The link drops, and bleak calls the disconnected callback."""
        self.is_connected = False
        self.disconnected_callback(self)


class HangingClient(StubClient):
    """A client whose disconnect() never returns."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cancelled = False

    async def disconnect(self):
        self.disconnect_calls += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class Clients:
    """Replaces BleakClient: hands out one client of each kind in turn, and keeps them."""

    def __init__(self, *kinds):
        self.kinds = list(kinds)
        self.made = []

    def __call__(self, address, disconnected_callback=None):
        client = self.kinds.pop(0)(address, disconnected_callback)
        self.made.append(client)
        return client


async def settle(cx):
    """Waits for the connection's background tasks."""
    while cx._background_tasks:
        await asyncio.gather(*cx._background_tasks)


async def test_a_dropped_client_is_disconnected_once():
    with patch("meshcore.ble_cx.BleakClient", Clients(StubClient)) as clients:
        cx = BLEConnection(address=ADDRESS)
        assert await cx.connect() == ADDRESS
        client = clients.made[0]

        client.drop()
        await cx.disconnect()
        await settle(cx)

    assert client.disconnect_calls == 1


async def test_a_disconnect_that_never_returns_holds_up_nothing():
    with patch("meshcore.ble_cx.BleakClient", Clients(HangingClient, StubClient)) as clients:
        cx = BLEConnection(address=ADDRESS)
        cx.DISCONNECT_TIMEOUT = 0.5
        assert await cx.connect() == ADDRESS
        hanging = clients.made[0]

        hanging.drop()  # returns: handle_disconnect waits on nothing
        await asyncio.sleep(0.05)
        assert hanging.disconnect_calls == 1

        # A new connect isn't held up by the release still waiting...
        assert await asyncio.wait_for(cx.connect(), timeout=0.2) == ADDRESS
        assert cx.client is clients.made[1]
        assert not hanging.cancelled

        # ...and the release gives up at its bound.
        await asyncio.wait_for(settle(cx), timeout=2)
        assert hanging.cancelled


async def test_a_reconnect_never_disconnects_the_new_client():
    with patch("meshcore.ble_cx.BleakClient", Clients(StubClient, StubClient)) as clients:
        cx = BLEConnection(address=ADDRESS)
        manager = ConnectionManager(cx, auto_reconnect=True)
        cx.set_disconnect_callback(manager.handle_disconnect)
        assert await manager.connect() == ADDRESS
        dropped = clients.made[0]

        dropped.drop()
        await settle(cx)
        await asyncio.wait_for(manager._reconnect_task, timeout=5)
        await settle(cx)

    new = clients.made[1]
    assert manager.is_connected
    assert cx.client is new
    assert dropped.disconnect_calls == 1
    assert new.disconnect_calls == 0
