"""
mccli.py : CLI interface to MeschCore BLE companion app
"""

import asyncio
import logging
import serial_asyncio_fast as serial_asyncio

# Get logger
logger = logging.getLogger("meshcore")


class SerialConnection:
    def __init__(self, port, baudrate, cx_dly=0.2):
        self.port = port
        self.baudrate = baudrate
        self.transport = None
        self.header = b""
        self.reader = None
        self._disconnect_callback = None
        self.cx_dly = cx_dly
        self._connected_event = asyncio.Event()

        self.frame_expected_size = 0
        self.inframe = b""
        self.header = b""

    class MCSerialClientProtocol(asyncio.Protocol):
        def __init__(self, cx):
            self.cx = cx

        def connection_made(self, transport):
            self.cx.transport = transport
            logger.debug('port opened')
            if isinstance(transport, serial_asyncio.SerialTransport) and transport.serial:
                transport.serial.rts = False  # You can manipulate Serial object via transport
            self.cx._connected_event.set()

        def data_received(self, data):
            self.cx.handle_rx(data)

        def connection_lost(self, exc):
            logger.debug('Serial port closed')
            self.cx._connected_event.clear()

            if self.cx._disconnect_callback:
                asyncio.create_task(self.cx._disconnect_callback("serial_disconnect"))

        def pause_writing(self):
            logger.debug("pause writing")

        def resume_writing(self):
            logger.debug("resume writing")

    async def connect(self):
        """
        Connects to the device
        """
        self._connected_event.clear()
        
        loop = asyncio.get_running_loop()
        await serial_asyncio.create_serial_connection(
            loop,
            lambda: self.MCSerialClientProtocol(self),
            self.port,
            baudrate=self.baudrate,
        )

        await self._connected_event.wait()
        logger.info("Serial Connection started")
        return self.port

    def set_reader(self, reader):
        self.reader = reader

    def handle_rx(self, data: bytearray):
        if len(self.header) == 0: # did not find start of frame yet
            # search start of frame (0x3e) in data
            idx = data.find(b"\x3e")
            if idx < 0: # no start of frame
                return
            self.header = data[0:1]
            data = data[1:]

        if len(self.header) < 3: # header not complete yet
            while len(self.header) < 3 and len(data) > 0:
                self.header = self.header + data[0:1]
                data = data[1:]
            if len(self.header) < 3: # still not complete
                return

            # get size and check
            self.frame_expected_size = int.from_bytes(self.header[1:], "little", signed=False)
            if self.frame_expected_size > 300 : # invalid size
                # reset inframe
                self.header = b""
                self.inframe = b""
                self.frame_expected_size = 0
                if len(data) > 0: # rerun handle_rx on remaining data
                    self.handle_rx(data)
                    return

        upbound = self.frame_expected_size - len(self.inframe)
        if len(data) < upbound:
            self.inframe = self.inframe + data
            # frame not complete, wait for next rx
            return

        self.inframe = self.inframe + data[0:upbound]
        data = data[upbound:]
        if self.reader is not None:
            # feed meshcore reader
            asyncio.create_task(self.reader.handle_rx(self.inframe))
        # reset inframe
        self.inframe = b""
        self.header = b""
        self.frame_expected_size = 0
        if len(data) > 0: # rerun handle_rx on remaining data
            self.handle_rx(data)

    async def send(self, data):
        if not self.transport:
            logger.error("Transport not connected, cannot send data")
            return
        size = len(data)
        pkt = b"\x3c" + size.to_bytes(2, byteorder="little") + data
        logger.debug(f"sending pkt : {pkt}")
        self.transport.write(pkt)

    async def disconnect(self):
        """Close the serial connection."""
        if self.transport:
            self.transport.close()
            self.transport = None
            self._connected_event.clear()
            logger.debug("Serial Connection closed")

    def set_disconnect_callback(self, callback):
        """Set callback to handle disconnections."""
        self._disconnect_callback = callback
