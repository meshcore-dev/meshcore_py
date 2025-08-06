"""
mccli.py : CLI interface to MeschCore BLE companion app
"""

import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakDeviceNotFoundError

# Get logger
logger = logging.getLogger("meshcore")

UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"


class BLEConnection:
    def __init__(self, address=None, client=None):
        """
        Constructor: specify address or an existing BleakClient.

        Args:
            address (str, optional): The Bluetooth address of the device.
            client (BleakClient, optional): An existing BleakClient instance.
        """
        self.address = address
        self._user_provided_address = address
        self.client = client
        self.rx_char = None
        self._disconnect_callback = None

    async def connect(self):
        """
        Connects to the device.

        If a BleakClient was provided to the constructor, it uses that.
        Otherwise, it will scan or connect based on the provided address.

        Returns:
            The address used for connection, or None on failure.
        """
        logger.debug(f"Connecting with client: {self.client}, address: {self.address}")

        if self.client:
            logger.debug("Using pre-configured BleakClient.")
            # If a client is already provided, ensure its disconnect callback is set
            assert isinstance(self.client, BleakClient)
            self.client.set_disconnected_callback(self.handle_disconnect)
            self.address = self.client.address
        else:

            def match_meshcore_device(_: BLEDevice, adv: AdvertisementData):
                """Filter to match MeshCore devices."""
                if adv.local_name and adv.local_name.startswith("MeshCore"):
                    if self.address is None or self.address in adv.local_name:
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
                self.client = BleakClient(
                    self.address, disconnected_callback=self.handle_disconnect
                )

        try:
            await self.client.connect()
        except BleakDeviceNotFoundError:
            return None
        except TimeoutError:
            return None

        await self.client.start_notify(UART_TX_CHAR_UUID, self.handle_rx)

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
        # Reset the address we found to what user specified
        # this allows to reconnect to the same device
        self.address = self._user_provided_address

        if self._disconnect_callback:
            asyncio.create_task(self._disconnect_callback("ble_disconnect"))

    def set_disconnect_callback(self, callback):
        """Set callback to handle disconnections."""
        self._disconnect_callback = callback

    def set_reader(self, reader):
        self.reader = reader

    def handle_rx(self, _: BleakGATTCharacteristic, data: bytearray):
        if self.reader is not None:
            asyncio.create_task(self.reader.handle_rx(data))

    async def send(self, data):
        if not self.client:
            logger.error("Client is not connected")
            return False
        if not self.rx_char:
            logger.error("RX characteristic not found")
            return False
        await self.client.write_gatt_char(self.rx_char, bytes(data), response=True)

    async def disconnect(self):
        """Disconnect from the BLE device."""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            logger.debug("BLE Connection closed")
