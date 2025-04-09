import asyncio
from typing import Dict, Any, Optional, Callable

from .events import EventDispatcher, MessageType, Event
from .reader import MessageReader
from .commands import CommandHandler, deprecated


class MeshCore:
    def __init__(self, cx):
        self.cx = cx
        self.dispatcher = EventDispatcher()
        self._reader = MessageReader(self.dispatcher)
        self.commands = CommandHandler()
        
        # Set up connections
        self.commands.set_connection(cx)
        
        # Initialize state
        self.contacts = {}
        self.self_info = {}
        self.time = 0
        
        # Set the message handler in the connection
        cx.set_mc(self)
        
    async def connect(self):
        # Start the event dispatcher
        await self.dispatcher.start()
        
        # Start the command handler
        await self.commands.start()
        
        # Send the initial app start
        return await self.commands.send_appstart()
    
    async def disconnect(self):
        # Stop the event dispatcher
        await self.dispatcher.stop()
        
        # Stop the command handler
        await self.commands.stop()
    
    # Internal method - called by the connection
    def handle_rx(self, data: bytearray):
        asyncio.create_task(self._reader.handle_rx(data))
    
    # Expose subscribe/wait capabilities from the event system 
    def subscribe(self, message_type, callback):
        return self.dispatcher.subscribe(message_type, callback)
    
    async def wait_for_event(self, message_type, timeout=None):
        return await self.dispatcher.wait_for_event(message_type, timeout)
    
    # Legacy method implementations that delegate to the command handler
    # using the deprecated decorator from commands.py
    
    @deprecated
    async def send(self, data, timeout=5):
        return await self.commands.send(data, timeout)
    
    @deprecated
    async def send_only(self, data):
        await self.commands.send_only(data)
    
    @deprecated
    async def send_appstart(self):
        return await self.commands.send_appstart()
    
    @deprecated
    async def send_device_query(self):
        return await self.commands.send_device_query()
    
    @deprecated
    async def send_advert(self, flood=False):
        return await self.commands.send_advert(flood)
    
    @deprecated
    async def set_name(self, name):
        return await self.commands.set_name(name)
    
    @deprecated
    async def set_coords(self, lat, lon):
        return await self.commands.set_coords(lat, lon)
    
    @deprecated
    async def reboot(self):
        return await self.commands.reboot()
    
    @deprecated
    async def get_bat(self):
        return await self.commands.get_bat()
    
    @deprecated
    async def get_time(self):
        time_result = await self.commands.get_time()
        if isinstance(time_result, int):
            self.time = time_result
        return self.time
    
    @deprecated
    async def set_time(self, val):
        return await self.commands.set_time(val)
    
    @deprecated
    async def set_tx_power(self, val):
        return await self.commands.set_tx_power(val)
    
    @deprecated
    async def set_radio(self, freq, bw, sf, cr):
        return await self.commands.set_radio(freq, bw, sf, cr)
    
    @deprecated
    async def set_tuning(self, rx_dly, af):
        return await self.commands.set_tuning(rx_dly, af)
    
    @deprecated
    async def set_devicepin(self, pin):
        return await self.commands.set_devicepin(pin)
    
    @deprecated
    async def get_contacts(self):
        await self.commands.get_contacts()
        contact_end = await self.dispatcher.wait_for_event(MessageType.CONTACT_END)
        if contact_end:
            self.contacts = contact_end.payload
        return self.contacts
    
    @deprecated
    async def ensure_contacts(self):
        if not self.contacts:
            await self.get_contacts()
    
    @deprecated
    async def reset_path(self, key):
        return await self.commands.reset_path(key)
    
    @deprecated
    async def share_contact(self, key):
        return await self.commands.share_contact(key)
    
    @deprecated
    async def export_contact(self, key=b""):
        return await self.commands.export_contact(key)
    
    @deprecated
    async def remove_contact(self, key):
        return await self.commands.remove_contact(key)
    
    @deprecated
    async def set_out_path(self, contact, path):
        contact["out_path"] = path
        contact["out_path_len"] = -1
        contact["out_path_len"] = int(len(path) / 2)
    
    @deprecated
    async def update_contact(self, contact):
        out_path_hex = contact["out_path"]
        out_path_hex = out_path_hex + (128-len(out_path_hex)) * "0" 
        adv_name_hex = contact["adv_name"].encode().hex()
        adv_name_hex = adv_name_hex + (64-len(adv_name_hex)) * "0"
        data = b"\x09" \
            + bytes.fromhex(contact["public_key"])\
            + contact["type"].to_bytes(1)\
            + contact["flags"].to_bytes(1)\
            + contact["out_path_len"].to_bytes(1, 'little', signed=True)\
            + bytes.fromhex(out_path_hex)\
            + bytes.fromhex(adv_name_hex)\
            + contact["last_advert"].to_bytes(4, 'little')\
            + int(contact["adv_lat"]*1e6).to_bytes(4, 'little', signed=True)\
            + int(contact["adv_lon"]*1e6).to_bytes(4, 'little', signed=True)
        return await self.send(data)
    
    @deprecated
    async def send_login(self, dst, pwd):
        await self.commands.send_login(dst, pwd)
        login_event = await self.dispatcher.wait_for_event(MessageType.LOGIN_SUCCESS, 0.1)
        if login_event:
            return True
        return await self.commands.send_login(dst, pwd)
        
    @deprecated
    async def wait_login(self, timeout=5):
        login_event = await self.dispatcher.wait_for_event(MessageType.LOGIN_SUCCESS, timeout)
        if login_event:
            return True
        login_failed = await self.dispatcher.wait_for_event(MessageType.LOGIN_FAILED, 0)
        if login_failed:
            return False
        return False
    
    @deprecated
    async def send_statusreq(self, dst):
        await self.commands.send_statusreq(dst)
    
    @deprecated
    async def wait_status(self, timeout=5):
        status_event = await self.dispatcher.wait_for_event(MessageType.STATUS_RESPONSE, timeout)
        if status_event:
            return status_event.payload
        return False
    
    @deprecated
    async def send_cmd(self, dst, cmd):
        timestamp = await self.get_time()
        return await self.commands.send_cmd(dst, cmd, timestamp.to_bytes(4, 'little'))
    
    @deprecated
    async def send_msg(self, dst, msg):
        timestamp = await self.get_time()
        result = await self.commands.send_msg(dst, msg, timestamp.to_bytes(4, 'little'))
        return result
    
    @deprecated
    async def send_chan_msg(self, chan, msg):
        timestamp = await self.get_time()
        return await self.commands.send_chan_msg(chan, msg, timestamp.to_bytes(4, 'little'))
    
    @deprecated
    async def get_msg(self):
        await self.commands.get_msg()
        
        # Wait for any message type that could be received
        message_types = [
            MessageType.CONTACT_MSG_RECV,
            MessageType.CHANNEL_MSG_RECV,
            MessageType.NO_MORE_MSGS
        ]
        
        for msg_type in message_types:
            event = await self.dispatcher.wait_for_event(msg_type, 0)
            if event:
                return event.payload
        
        return False
    
    @deprecated
    async def wait_msg(self, timeout=-1):
        msg_event = await self.dispatcher.wait_for_event(MessageType.MESSAGES_WAITING, timeout)
        return msg_event is not None
    
    @deprecated
    async def wait_ack(self, timeout=6):
        ack_event = await self.dispatcher.wait_for_event(MessageType.ACK, timeout)
        return ack_event is not None
    
    @deprecated
    async def send_cli(self, cmd):
        return await self.commands.send_cli(cmd)