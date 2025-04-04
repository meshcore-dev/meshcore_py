""" 
    mccli.py : CLI interface to MeschCore BLE companion app
"""
import asyncio
import sys

from meshcore import printerr

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakDeviceNotFoundError

UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

class BLEConnection:
    def __init__(self, address):
        """ Constructor : specify address """
        self.address = address
        self.client = None
        self.rx_char = None
        self.mc = None

    async def connect(self):
        """
        Connects to the device

        Returns : the address used for connection
        """
        def match_meshcore_device(_: BLEDevice, adv: AdvertisementData):
            """ Filter to mach MeshCore devices """
            if not adv.local_name is None\
                    and adv.local_name.startswith("MeshCore")\
                    and (self.address is None or self.address in adv.local_name) :
                return True
            return False

        if self.address is None or self.address == "" or len(self.address.split(":")) != 6 :
            scanner = BleakScanner()
            printerr("Scanning for devices")
            device = await scanner.find_device_by_filter(match_meshcore_device)
            if device is None :
                return None
            printerr(f"Found device : {device}")
            self.client = BleakClient(device)
            self.address = self.client.address
        else:
            self.client = BleakClient(self.address)

        try:
            await self.client.connect(disconnected_callback=self.handle_disconnect)
        except BleakDeviceNotFoundError:
            return None
        except TimeoutError:
            return None

        await self.client.start_notify(UART_TX_CHAR_UUID, self.handle_rx)

        nus = self.client.services.get_service(UART_SERVICE_UUID)
        self.rx_char = nus.get_characteristic(UART_RX_CHAR_UUID)

        printerr("BLE Connexion started")
        return self.address

    def handle_disconnect(self, _: BleakClient):
        """ Callback to handle disconnection """
        printerr ("Device was disconnected, goodbye.")
        # cancelling all tasks effectively ends the program
        for task in asyncio.all_tasks():
            task.cancel()

    def set_mc(self, mc) :
        self.mc = mc

    def handle_rx(self, _: BleakGATTCharacteristic, data: bytearray):
        if not self.mc is None:
            self.mc.handle_rx(data)

    async def send(self, data):
        await self.client.write_gatt_char(self.rx_char, bytes(data), response=False)
