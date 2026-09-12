"""
mccli.py : CLI interface to MeschCore BLE companion app
"""

import asyncio
import logging
from typing import Optional


# Make bleak optional - only fail if BLE operations are attempted
try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.characteristic import BleakGATTCharacteristic
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
    from bleak.exc import BleakDeviceNotFoundError
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False
    BleakClient = None
    BleakGATTCharacteristic = None

# Get logger
logger = logging.getLogger("meshcore")

UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

class BLEConnection:
    # Upper bound on a single write (lock acquisition included). Healthy writes
    # measured 0.06-0.17s against real hardware; observed stalls ran 20s to
    # minutes, so this preempts them rather than waiting for CoreBluetooth.
    WRITE_TIMEOUT = 10.0

    def __init__(self, address=None, device=None, client=None, pin=None):
        """
        Constructor: specify address or an existing BleakClient.

        Args:
            address (str, optional): The Bluetooth address of the device.
            device (BLEDevice, optional): A BLEDevice instance.
            client (BleakClient, optional): An existing BleakClient instance.
            pin (str, optional): PIN for BLE pairing authentication.
        """
        if not BLEAK_AVAILABLE:
          raise ImportError(
              f"BLE requires 'bleak' package to be installed."
          )

        self.address = address
        self._user_provided_address = address
        self.client = client
        self._user_provided_client = client
        self.device = device
        self._user_provided_device = device
        self.pin = pin
        self.rx_char = None
        self._disconnect_callback = None
        self._background_tasks: set[asyncio.Task] = set()
        self._write_lock_obj: Optional[asyncio.Lock] = None

    @property
    def _write_lock(self) -> asyncio.Lock:
        """Serialises write_gatt_char().

        Two overlapping writes to the same characteristic drop the link outright
        (observed on macOS/CoreBluetooth: "BLE write failed: 19", connection
        gone). Nothing above this layer guarantees callers are sequential --
        schedulers, health checks and user commands all issue independently --
        so the transport has to enforce it.

        Lazily created so it binds to the running loop, mirroring the
        _mesh_request_lock property in commands/base.py. Read through getattr so
        an instance built without __init__ still works.
        """
        lock = getattr(self, "_write_lock_obj", None)
        if lock is None:
            lock = asyncio.Lock()
            self._write_lock_obj = lock
        return lock

    def _spawn_background(self, coro) -> asyncio.Task:
        """Create a tracked background task (prevents GC of fire-and-forget tasks)."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _cleanup_stale_client(self):
        """Best-effort disconnect of an existing self.client before it is replaced.

        connect() always overwrites self.client with a fresh BleakClient on
        reconnect. If the previous client's GATT notification subscription
        (start_notify on UART_TX_CHAR_UUID) is never torn down, the stale
        registration survives at the BlueZ D-Bus level and every future
        notification fires twice: once for the stale registration, once for
        the new one.
        """
        if self.client is not None:
            try:
                if self.client.is_connected:
                    await self.client.disconnect()
            except Exception:
                logger.debug("Best-effort cleanup of stale BLE client failed", exc_info=True)

    async def connect(self):
        """
        Connects to the device.

        If a BleakClient was provided to the constructor, it uses that.
        Otherwise, it will scan or connect based on the provided address.

        Returns:
            The address used for connection, or None on failure.
        """
        logger.debug(f"Connecting with client: {self.client}, address: {self.address}, device: {self.device}")

        await self._cleanup_stale_client()

        if self.client:
            logger.debug("Using pre-configured BleakClient.")
            assert isinstance(self.client, BleakClient)
            if self.client.is_connected :
                logger.error("Client is already connected !!! weird")
                self.address = self.client.address
                return self.address
            self.address = self.client.address
            # If a client is provided it surely does not have disconnect callback
            # so recreate it as set_disconnected_callback can't be used anymore ...
            self.client = BleakClient(self.address, disconnected_callback=self.handle_disconnect)
        elif self.device:
            logger.debug("Directly using a passed device.")
            self.client = BleakClient(self.device, disconnected_callback=self.handle_disconnect)
        else:

            def match_meshcore_device(d: BLEDevice, adv: AdvertisementData):
                """Filter to match MeshCore devices."""
                if adv.local_name and adv.local_name.startswith("MeshCore"):
                    if self.address is None or self.address in adv.local_name:
                        return True
                if d and d.address == self.address:
                    return True
                return False

            if self.address is None or ":" not in self.address:
                logger.info("Scanning for devices...")
                device = await BleakScanner.find_device_by_filter(match_meshcore_device)
                if device is None:
                    logger.warning("No MeshCore device found during scan.")
                    return None
                logger.info(f"Found device: {device}")
                self.client = BleakClient(
                    device, disconnected_callback=self.handle_disconnect
                )
                self.address = self.client.address
            else:
                logger.debug("Connecting using provided address")
                self.client = BleakClient(
                    self.address, disconnected_callback=self.handle_disconnect
                )

        try:
            await self.client.connect()
            
            # Perform pairing if PIN is provided
            if self.pin is not None:
                logger.debug(f"Attempting BLE pairing with PIN")
                try:
                    await self.client.pair()
                    logger.info("BLE pairing successful")
                except Exception as e:
                    logger.error(f"BLE pairing failed: {e}")
                    # A failed pairing leaves the transport in a half-usable
                    # state — re-raise so the caller gets a clean failure
                    # instead of a silently degraded connection.
                    await self.client.disconnect()
                    raise
                    
        except BleakDeviceNotFoundError:
            return None
        except TimeoutError:
            return None

        try:
            await self.client.start_notify(UART_TX_CHAR_UUID, self.handle_rx)
        except AttributeError :
            if self.client :
                await self.client.disconnect()
            logger.info("Connection is not established, need to restart it")
            logger.debug("in ble_cx.connect()")
            return None

        nus = self.client.services.get_service(UART_SERVICE_UUID)
        if nus is None:
            logger.error("Could not find UART service")
            return None
        self.rx_char = nus.get_characteristic(UART_RX_CHAR_UUID)

        logger.info("BLE Connection started")
        return self.address

    def handle_disconnect(self, client: BleakClient):
        """Callback to handle disconnection"""
        logger.debug(
            f"BLE device disconnected: {client.address} (is_connected: {client.is_connected})"
        )
        # Reset the address/client/device we found to what user specified
        # this allows to reconnect to the same device
        self.address = self._user_provided_address
        self.client = self._user_provided_client
        self.device = self._user_provided_device

        # Re-register disconnect callback on the reset client so subsequent
        # disconnects after a reconnect cycle are still detected.
        if self.client is not None and hasattr(self.client, 'set_disconnected_callback'):
            try:
                self.client.set_disconnected_callback(self.handle_disconnect)
            except Exception:
                # set_disconnected_callback may not be available on all bleak
                # versions; the next connect() call will re-create the client
                # with the callback anyway.
                pass

        if self._disconnect_callback:
            self._spawn_background(self._disconnect_callback("ble_disconnect"))

    def set_disconnect_callback(self, callback):
        """Set callback to handle disconnections."""
        self._disconnect_callback = callback

    def set_reader(self, reader):
        self.reader = reader

    def handle_rx(self, _: BleakGATTCharacteristic, data: bytearray):
        if self.reader is not None:
            self._spawn_background(self.reader.handle_rx(data))

    async def _write_locked(self, data):
        async with self._write_lock:
            await self.client.write_gatt_char(self.rx_char, bytes(data), response=True)

    async def send(self, data):
        if not self.client:
            logger.error("Client is not connected")
            if self._disconnect_callback:
                await self._disconnect_callback("ble_transport_lost")
            return False
        if not self.rx_char:
            logger.error("RX characteristic not found")
            return False
        # Bound the whole acquire-plus-write. A stalled write has been seen to
        # hang for minutes, and CommandHandler's own timeout does not cover this
        # -- it starts only after _sender_func returns -- so without a bound the
        # serialising lock would queue every other command behind the stall
        # indefinitely, with nothing logged and no disconnect raised. Turning one
        # hung command into a silent whole-client stall would be worse than the
        # overlap the lock exists to prevent.
        try:
            await asyncio.wait_for(self._write_locked(data), timeout=self.WRITE_TIMEOUT)
        except asyncio.TimeoutError:
            # Do not simply release and carry on: the underlying write may still
            # be in flight, and a second write racing it re-creates the exact
            # overlap that kills the link. Tear the connection down so the
            # reconnect path takes over -- bounded and self-healing.
            logger.warning(f"BLE write timed out after {self.WRITE_TIMEOUT}s")
            if self._disconnect_callback:
                await self._disconnect_callback("ble_write_timeout")
            return False
        except Exception as exc:
            logger.warning(f"BLE write failed: {exc}")
            if self._disconnect_callback:
                await self._disconnect_callback(f"ble_write_failed: {exc}")
            return False

    async def disconnect(self):
        """Disconnect from the BLE device."""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            logger.debug("BLE Connection closed")
