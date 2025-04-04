""" 
    mccli.py : CLI interface to MeschCore BLE companion app
"""
import asyncio
import sys
import serial_asyncio

from meshcore import printerr

class SerialConnection:
    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.frame_started = False
        self.frame_size = 0
        self.header = b""
        self.inframe = b""

    class MCSerialClientProtocol(asyncio.Protocol):
        def __init__(self, cx):
            self.cx = cx

        def connection_made(self, transport):
            self.cx.transport = transport
#            printerr('port opened')
            transport.serial.rts = False  # You can manipulate Serial object via transport
    
        def data_received(self, data):
#            printerr('data received')
            self.cx.handle_rx(data)    
    
        def connection_lost(self, exc):
            printerr('port closed')
    
        def pause_writing(self):
            printerr('pause writing')
    
        def resume_writing(self):
            printerr('resume writing')

    async def connect(self):
        """
        Connects to the device
        """
        loop = asyncio.get_running_loop()
        await serial_asyncio.create_serial_connection(
                loop, lambda: self.MCSerialClientProtocol(self), 
                self.port, baudrate=self.baudrate)

        printerr("Serial Connexion started")
        return self.port

    def set_mc(self, mc) :
        self.mc = mc

    def handle_rx(self, data: bytearray):
        headerlen = len(self.header)
        framelen = len(self.inframe)
        if not self.frame_started : # wait start of frame
            if len(data) >= 3 - headerlen:
                self.header = self.header + data[:3-headerlen]
                self.frame_started = True
                self.frame_size = int.from_bytes(self.header[1:], byteorder='little')
                self.handle_rx(data[3-headerlen:])
            else:
                self.header = self.header + data
        else:
            if framelen + len(data) < self.frame_size:
                self.inframe = self.inframe + data
            else:
                self.inframe = self.inframe + data[:self.frame_size-framelen]
                if not self.mc is None:
                    self.mc.handle_rx(self.inframe)
                self.frame_started = False
                self.header = b""
                self.inframe = b""
                if framelen + len(data) > self.frame_size:
                    self.handle_rx(data[self.frame_size-framelen:])

    async def send(self, data):
        size = len(data)
        pkt = b"\x3c" + size.to_bytes(2, byteorder="little") + data
#        printerr(f"sending pkt : {pkt}")
        self.transport.write(pkt)
