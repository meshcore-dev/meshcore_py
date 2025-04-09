import functools
import asyncio
import logging
import warnings
import time
from typing import Any, Callable, Awaitable, Optional, Union
from .events import EventType

logger = logging.getLogger("meshcore")

class CommandError(Exception):
    def __init__(self, details=None):
        self.details = details
        super().__init__(f"Command error: {details}")

def deprecated(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        warnings.warn(
            f"Method {func.__name__} is deprecated. Use commands.{func.__name__} instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return await func(*args, **kwargs)
    return wrapper


class CommandHandler:
    def __init__(self):
        self._sender_func = None
        self._reader = None
        self.dispatcher = None
        
    def set_connection(self, connection):
        async def sender(data):
            await connection.send(data)
        self._sender_func = sender
        
    def set_reader(self, reader):
        self._reader = reader
        
    def set_dispatcher(self, dispatcher):
        self.dispatcher = dispatcher
        
    async def send(self, data, expected_events=None, timeout=5.0):
        if not self.dispatcher:
            raise RuntimeError("Dispatcher not set, cannot send commands")
            
        if self._sender_func:
            logger.debug(f"Sending raw data: {data.hex() if isinstance(data, bytes) else data}")
            await self._sender_func(data)
        
        if expected_events:
            try:
                # Convert single event to list if needed
                if not isinstance(expected_events, list):
                    expected_events = [expected_events]
                    
                logger.debug(f"Waiting for events {expected_events}, timeout={timeout}")
                for event_type in expected_events:
                    event = await self.dispatcher.wait_for_event(event_type, timeout)
                    if event:
                        return event.payload
                return False
            except asyncio.TimeoutError:
                logger.debug(f"Command timed out {data}")
                return False
            except Exception as e:
                logger.debug(f"Command error: {e}")
                return {"error": str(e)}
        return True
        
        
    async def send_appstart(self):
        logger.debug("Sending appstart command")
        b1 = bytearray(b'\x01\x03      mccli')
        return await self.send(b1, [EventType.SELF_INFO])
        
    async def send_device_query(self):
        logger.debug("Sending device query command")
        return await self.send(b"\x16\x03", [EventType.DEVICE_INFO, EventType.ERROR])
        
    async def send_advert(self, flood=False):
        logger.debug(f"Sending advertisement command (flood={flood})")
        if flood:
            return await self.send(b"\x07\x01", [EventType.OK, EventType.ERROR])
        else:
            return await self.send(b"\x07", [EventType.OK, EventType.ERROR])
            
    async def set_name(self, name):
        logger.debug(f"Setting device name to: {name}")
        return await self.send(b'\x08' + name.encode("ascii"), [EventType.OK, EventType.ERROR])
        
    async def set_coords(self, lat, lon):
        logger.debug(f"Setting coordinates to: lat={lat}, lon={lon}")
        return await self.send(b'\x0e'\
                + int(lat*1e6).to_bytes(4, 'little', signed=True)\
                + int(lon*1e6).to_bytes(4, 'little', signed=True)\
                + int(0).to_bytes(4, 'little'), [EventType.OK, EventType.ERROR])
                
    async def reboot(self):
        logger.debug("Sending reboot command")
        return await self.send(b'\x13reboot')
        
    async def get_bat(self):
        logger.debug("Getting battery information")
        return await self.send(b'\x14', [EventType.BATTERY, EventType.ERROR])
        
    async def get_time(self):
        logger.debug("Getting device time")
        return await self.send(b"\x05", [EventType.CURRENT_TIME, EventType.ERROR])
        
    async def set_time(self, val):
        logger.debug(f"Setting device time to: {val}")
        return await self.send(b"\x06" + int(val).to_bytes(4, 'little'), [EventType.OK, EventType.ERROR])
        
    async def set_tx_power(self, val):
        logger.debug(f"Setting TX power to: {val}")
        return await self.send(b"\x0c" + int(val).to_bytes(4, 'little'), [EventType.OK, EventType.ERROR])
        
    async def set_radio(self, freq, bw, sf, cr):
        logger.debug(f"Setting radio params: freq={freq}, bw={bw}, sf={sf}, cr={cr}")
        return await self.send(b"\x0b" \
                + int(float(freq)*1000).to_bytes(4, 'little')\
                + int(float(bw)*1000).to_bytes(4, 'little')\
                + int(sf).to_bytes(1, 'little')\
                + int(cr).to_bytes(1, 'little'), [EventType.OK, EventType.ERROR])
                
    async def set_tuning(self, rx_dly, af):
        logger.debug(f"Setting tuning params: rx_dly={rx_dly}, af={af}")
        return await self.send(b"\x15" \
                + int(rx_dly).to_bytes(4, 'little')\
                + int(af).to_bytes(4, 'little')\
                + int(0).to_bytes(1, 'little')\
                + int(0).to_bytes(1, 'little'), [EventType.OK, EventType.ERROR])
                
    async def set_devicepin(self, pin):
        logger.debug(f"Setting device PIN to: {pin}")
        return await self.send(b"\x25" \
                + int(pin).to_bytes(4, 'little'), [EventType.OK, EventType.ERROR])
                
    async def get_contacts(self):
        logger.debug("Getting contacts")
        return await self.send(b"\x04", [EventType.CONTACTS, EventType.ERROR])
        
    async def reset_path(self, key):
        logger.debug(f"Resetting path for contact: {key.hex() if isinstance(key, bytes) else key}")
        data = b"\x0D" + key
        return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def share_contact(self, key):
        logger.debug(f"Sharing contact: {key.hex() if isinstance(key, bytes) else key}")
        data = b"\x10" + key
        return await self.send(data, [EventType.CONTACT_SHARE, EventType.ERROR])
        
    async def export_contact(self, key=b""):
        logger.debug(f"Exporting contact: {key.hex() if key else 'all'}")
        data = b"\x11" + key
        return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def remove_contact(self, key):
        logger.debug(f"Removing contact: {key.hex() if isinstance(key, bytes) else key}")
        data = b"\x0f" + key
        return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def get_msg(self):
        logger.debug("Requesting pending messages")
        return await self.send(b"\x0A", [EventType.CONTACT_MSG_RECV, EventType.CHANNEL_MSG_RECV, EventType.ERROR], 1)
        
    async def send_login(self, dst, pwd):
        logger.debug(f"Sending login request to: {dst.hex() if isinstance(dst, bytes) else dst}")
        data = b"\x1a" + dst + pwd.encode("ascii")
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
    async def send_statusreq(self, dst):
        logger.debug(f"Sending status request to: {dst.hex() if isinstance(dst, bytes) else dst}")
        data = b"\x1b" + dst
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
    async def send_cmd(self, dst, cmd, timestamp=None):
        logger.debug(f"Sending command to {dst.hex() if isinstance(dst, bytes) else dst}: {cmd}")
        
        # Default to current time if timestamp not provided
        if timestamp is None:
            import time
            timestamp = int(time.time()).to_bytes(4, 'little')
            
        data = b"\x02\x01\x00" + timestamp + dst + cmd.encode("ascii")
        return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def send_msg(self, dst, msg, timestamp=None):
        logger.debug(f"Sending message to {dst.hex() if isinstance(dst, bytes) else dst}: {msg}")
        
        # Default to current time if timestamp not provided
        if timestamp is None:
            import time
            timestamp = int(time.time()).to_bytes(4, 'little')
            
        data = b"\x02\x00\x00" + timestamp + dst + msg.encode("ascii")
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
    async def send_chan_msg(self, chan, msg, timestamp=None):
        logger.debug(f"Sending channel message to channel {chan}: {msg}")
        
        # Default to current time if timestamp not provided
        if timestamp is None:
            import time
            timestamp = int(time.time()).to_bytes(4, 'little')
            
        data = b"\x03\x00" + chan.to_bytes(1, 'little') + timestamp + msg.encode("ascii")
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
    async def send_cli(self, cmd):
        logger.debug(f"Sending CLI command: {cmd}")
        data = b"\x32" + cmd.encode('ascii')
        return await self.send(data, [EventType.CLI_RESPONSE, EventType.ERROR])