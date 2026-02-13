"""
mccli.py : CLI interface to MeschCore BLE companion app
"""

import asyncio
import logging

# Get logger
logger = logging.getLogger("meshcore")

# TCP disconnect detection threshold
TCP_DISCONNECT_THRESHOLD = 5


class TCPConnection:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.transport = None
        self.frame_started = False
        self._disconnect_callback = None
        self._send_count = 0
        self._receive_count = 0
        self.frame_expected_size = 0
        self.header = b""
        self.inframe = b""

    class MCClientProtocol(asyncio.Protocol):
        def __init__(self, cx):
            self.cx = cx

        def connection_made(self, transport):
            self.cx.transport = transport
            # Reset counters on new connection
            self.cx._send_count = 0
            self.cx._receive_count = 0
            logger.debug("connection established")

        def data_received(self, data):
            logger.debug("data received")
            self.cx._receive_count += 1
            self.cx.handle_rx(data)

        def error_received(self, exc):
            logger.error(f"Error received: {exc}")

        def connection_lost(self, exc):
            logger.debug("TCP server closed the connection")
            if self.cx._disconnect_callback:
                asyncio.create_task(self.cx._disconnect_callback("tcp_disconnect"))

    async def connect(self):
        """
        Connects to the device
        """
        loop = asyncio.get_running_loop()
        await loop.create_connection(
            lambda: self.MCClientProtocol(self), self.host, self.port
        )

        logger.info("TCP Connection started")
        future = asyncio.Future()
        future.set_result(self.host)

        return future

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
        if len(data) < upbound :
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
            if self._disconnect_callback:
                await self._disconnect_callback("tcp_transport_lost")
            return

        self._send_count += 1

        # Check if we've sent packets without any responses
        if self._send_count - self._receive_count >= TCP_DISCONNECT_THRESHOLD:
            logger.debug(
                f"TCP disconnect detected: sent {self._send_count}, received {self._receive_count}"
            )
            if self._disconnect_callback:
                await self._disconnect_callback("tcp_no_response")
            return

        size = len(data)
        pkt = b"\x3c" + size.to_bytes(2, byteorder="little") + data
        logger.debug(f"sending pkt : {pkt}")
        self.transport.write(pkt)

    async def disconnect(self):
        """Close the TCP connection."""
        if self.transport:
            self.transport.close()
            self.transport = None
            logger.debug("TCP Connection closed")

    def set_disconnect_callback(self, callback):
        """Set callback to handle disconnections."""
        self._disconnect_callback = callback
