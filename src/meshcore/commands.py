import asyncio
import logging
import random
from typing import Any, Dict, List, Optional, Union
from .events import Event, EventType

# Define types for destination parameters
DestinationType = Union[bytes, str, Dict[str, Any]]
            
logger = logging.getLogger("meshcore")

def _validate_destination(dst: DestinationType, prefix_length: int = 6) -> bytes:
    """
    Validates and converts a destination to a bytes object.
    
    Args:
        dst: The destination, which can be:
            - str: Hex string representation of a public key
            - dict: Contact object with a "public_key" field
        prefix_length: The length of the prefix to use (default: 6 bytes)
            
    Returns:
        bytes: The destination public key as a bytes object
        
    Raises:
        ValueError: If dst is invalid or doesn't contain required fields
    """
    if isinstance(dst, bytes):
        # Already bytes, use directly
        return dst[:prefix_length] 
    elif isinstance(dst, str):
        # Hex string, convert to bytes
        try:
            return bytes.fromhex(dst)[:prefix_length]
        except ValueError:
            raise ValueError(f"Invalid public key hex string: {dst}")
    elif isinstance(dst, dict):
        # Contact object, extract public_key
        if "public_key" not in dst:
            raise ValueError("Contact object must have a 'public_key' field")
        try:
            return bytes.fromhex(dst["public_key"])[:prefix_length]
        except ValueError:
            raise ValueError(f"Invalid public_key in contact: {dst['public_key']}")
    else:
        raise ValueError(f"Destination must be a public key string or contact object, got: {type(dst)}")

class CommandHandler:
    DEFAULT_TIMEOUT = 5.0
    
    def __init__(self, default_timeout: Optional[float] = None):
        self._sender_func = None
        self._reader = None
        self.dispatcher = None
        self.default_timeout = default_timeout if default_timeout is not None else self.DEFAULT_TIMEOUT
        
    def set_connection(self, connection: Any) -> None:
        async def sender(data: bytes) -> None:
            await connection.send(data)
        self._sender_func = sender
        
    def set_reader(self, reader: Any) -> None:
        self._reader = reader
        
    def set_dispatcher(self, dispatcher: Any) -> None:
        self.dispatcher = dispatcher
        
    async def send(self, data: bytes, expected_events: Optional[Union[EventType, List[EventType]]] = None, 
                timeout: Optional[float] = None) -> Event:
        """
        Send a command and wait for expected event responses.
        
        Args:
            data: The data to send
            expected_events: EventType or list of EventTypes to wait for
            timeout: Timeout in seconds, or None to use default_timeout
            
        Returns:
            Event: The full event object that was received in response to the command
        """
        if not self.dispatcher:
            raise RuntimeError("Dispatcher not set, cannot send commands")
            
        # Use the provided timeout or fall back to default_timeout
        timeout = timeout if timeout is not None else self.default_timeout
            
        if self._sender_func:
            logger.debug(f"Sending raw data: {data.hex() if isinstance(data, bytes) else data}")
            await self._sender_func(data)
        
        if expected_events:
            try:
                # Convert single event to list if needed
                if not isinstance(expected_events, list):
                    expected_events = [expected_events]
                    
                logger.debug(f"Waiting for events {expected_events}, timeout={timeout}")
                
                # Create futures for all expected events
                futures = []
                for event_type in expected_events:
                    future = asyncio.create_task(
                        self.dispatcher.wait_for_event(event_type, {}, timeout)
                    )
                    futures.append(future)
                
                # Wait for the first event to complete or all to timeout
                done, pending = await asyncio.wait(
                    futures, 
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Cancel all pending futures
                for future in pending:
                    future.cancel()
                
                # Check if any future completed successfully
                for future in done:
                    event = await future
                    if event:
                        return event
                        
                # Create an error event when no event is received
                return Event(EventType.ERROR, {"reason": "no_event_received"})
            except asyncio.TimeoutError:
                logger.debug(f"Command timed out {data}")
                return Event(EventType.ERROR, {"reason": "timeout"})
            except Exception as e:
                logger.debug(f"Command error: {e}")
                return Event(EventType.ERROR, {"error": str(e)})
        # For commands that don't expect events, return a success event
        return Event(EventType.OK, {})
        
        
    async def send_appstart(self) -> Event:
        logger.debug("Sending appstart command")
        b1 = bytearray(b'\x01\x03      mccli')
        return await self.send(b1, [EventType.SELF_INFO])
        
    async def send_device_query(self) -> Event:
        logger.debug("Sending device query command")
        return await self.send(b"\x16\x03", [EventType.DEVICE_INFO, EventType.ERROR])
        
    async def send_advert(self, flood: bool = False) -> Event:
        logger.debug(f"Sending advertisement command (flood={flood})")
        if flood:
            return await self.send(b"\x07\x01", [EventType.OK, EventType.ERROR])
        else:
            return await self.send(b"\x07", [EventType.OK, EventType.ERROR])
            
    async def set_name(self, name: str) -> Event:
        logger.debug(f"Setting device name to: {name}")
        return await self.send(b'\x08' + name.encode("utf-8"), [EventType.OK, EventType.ERROR])
        
    async def set_coords(self, lat: float, lon: float) -> Event:
        logger.debug(f"Setting coordinates to: lat={lat}, lon={lon}")
        return await self.send(b'\x0e'\
                + int(lat*1e6).to_bytes(4, 'little', signed=True)\
                + int(lon*1e6).to_bytes(4, 'little', signed=True)\
                + int(0).to_bytes(4, 'little'), [EventType.OK, EventType.ERROR])
                
    async def reboot(self) -> Event:
        logger.debug("Sending reboot command")
        return await self.send(b'\x13reboot')
        
    async def get_bat(self) -> Event:
        logger.debug("Getting battery information")
        return await self.send(b'\x14', [EventType.BATTERY, EventType.ERROR])
        
    async def get_time(self) -> Event:
        logger.debug("Getting device time")
        return await self.send(b"\x05", [EventType.CURRENT_TIME, EventType.ERROR])
        
    async def set_time(self, val: int) -> Event:
        logger.debug(f"Setting device time to: {val}")
        return await self.send(b"\x06" + int(val).to_bytes(4, 'little'), [EventType.OK, EventType.ERROR])
        
    async def set_tx_power(self, val: int) -> Event:
        logger.debug(f"Setting TX power to: {val}")
        return await self.send(b"\x0c" + int(val).to_bytes(4, 'little'), [EventType.OK, EventType.ERROR])
        
    async def set_radio(self, freq: float, bw: float, sf: int, cr: int) -> Event:
        logger.debug(f"Setting radio params: freq={freq}, bw={bw}, sf={sf}, cr={cr}")
        return await self.send(b"\x0b" \
                + int(float(freq)*1000).to_bytes(4, 'little')\
                + int(float(bw)*1000).to_bytes(4, 'little')\
                + int(sf).to_bytes(1, 'little')\
                + int(cr).to_bytes(1, 'little'), [EventType.OK, EventType.ERROR])
                
    async def set_tuning(self, rx_dly: int, af: int) -> Event:
        logger.debug(f"Setting tuning params: rx_dly={rx_dly}, af={af}")
        return await self.send(b"\x15" \
                + int(rx_dly).to_bytes(4, 'little')\
                + int(af).to_bytes(4, 'little')\
                + int(0).to_bytes(1, 'little')\
                + int(0).to_bytes(1, 'little'), [EventType.OK, EventType.ERROR])
                
    async def set_devicepin(self, pin: int) -> Event:
        logger.debug(f"Setting device PIN to: {pin}")
        return await self.send(b"\x25" \
                + int(pin).to_bytes(4, 'little'), [EventType.OK, EventType.ERROR])
                
    async def get_contacts(self) -> Event:
        logger.debug("Getting contacts")
        return await self.send(b"\x04", [EventType.CONTACTS, EventType.ERROR])
        
    async def reset_path(self, key: DestinationType) -> Event:
        key_bytes = _validate_destination(key, prefix_length=32)
        logger.debug(f"Resetting path for contact: {key_bytes.hex()}")
        data = b"\x0D" + key_bytes
        return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def share_contact(self, key: DestinationType) -> Event:
        key_bytes = _validate_destination(key, prefix_length=32)
        logger.debug(f"Sharing contact: {key_bytes.hex()}")
        data = b"\x10" + key_bytes
        return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def export_contact(self, key: Optional[DestinationType] = None) -> Event:
        if key:
            key_bytes = _validate_destination(key, prefix_length=32)
            logger.debug(f"Exporting contact: {key_bytes.hex()}")
            data = b"\x11" + key_bytes
        else:
            logger.debug("Exporting node")
            data = b"\x11"
        return await self.send(data, [EventType.CONTACT_URI, EventType.ERROR])
        
    async def remove_contact(self, key: DestinationType) -> Event:
        key_bytes = _validate_destination(key, prefix_length=32)
        logger.debug(f"Removing contact: {key_bytes.hex()}")
        data = b"\x0f" + key_bytes
        return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def change_contact_path (self, contact, path) -> Event:
        out_path_hex = path
        out_path_len = int(len(path) / 2)
        out_path_hex = out_path_hex + (128-len(out_path_hex)) * "0" 
        adv_name_hex = contact["adv_name"].encode().hex()
        adv_name_hex = adv_name_hex + (64-len(adv_name_hex)) * "0"
        data = b"\x09" \
            + bytes.fromhex(contact["public_key"])\
            + contact["type"].to_bytes(1)\
            + contact["flags"].to_bytes(1)\
            + out_path_len.to_bytes(1, 'little', signed=True)\
            + bytes.fromhex(out_path_hex)\
            + bytes.fromhex(adv_name_hex)\
            + contact["last_advert"].to_bytes(4, 'little')\
            + int(contact["adv_lat"]*1e6).to_bytes(4, 'little', signed=True)\
            + int(contact["adv_lon"]*1e6).to_bytes(4, 'little', signed=True)
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def get_msg(self, timeout: Optional[float] = 1) -> Event:
        logger.debug("Requesting pending messages")
        return await self.send(b"\x0A", [EventType.CONTACT_MSG_RECV, EventType.CHANNEL_MSG_RECV, EventType.ERROR, EventType.NO_MORE_MSGS], timeout)
        
    async def send_login(self, dst: DestinationType, pwd: str) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        logger.debug(f"Sending login request to: {dst_bytes.hex()}")
        data = b"\x1a" + dst_bytes + pwd.encode("utf-8")
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
    async def send_logout(self, dst: DestinationType) -> Event:
         dst_bytes = _validate_destination(dst, prefix_length=32)
         self.login_resp = asyncio.Future()
         data = b"\x1d" + dst_bytes
         return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def send_statusreq(self, dst: DestinationType) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        logger.debug(f"Sending status request to: {dst_bytes.hex()}")
        data = b"\x1b" + dst_bytes
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
    async def send_cmd(self, dst: DestinationType, cmd: str, timestamp: Optional[int] = None) -> Event:
        dst_bytes = _validate_destination(dst)
        logger.debug(f"Sending command to {dst_bytes.hex()}: {cmd}")
        
        if timestamp is None:
            import time
            timestamp = int(time.time())
            
        data = b"\x02\x01\x00" + timestamp.to_bytes(4, 'little') + dst_bytes + cmd.encode("utf-8")
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
    async def send_msg(self, dst: DestinationType, msg: str, timestamp: Optional[int] = None) -> Event:
        dst_bytes = _validate_destination(dst)
        logger.debug(f"Sending message to {dst_bytes.hex()}: {msg}")
        
        if timestamp is None:
            import time
            timestamp = int(time.time())
            
        data = b"\x02\x00\x00" + timestamp.to_bytes(4, 'little') + dst_bytes + msg.encode("utf-8")
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
    async def send_chan_msg(self, chan, msg, timestamp=None) -> Event:
        logger.debug(f"Sending channel message to channel {chan}: {msg}")
        
        # Default to current time if timestamp not provided
        if timestamp is None:
            import time
            timestamp = int(time.time()).to_bytes(4, 'little')
            
        data = b"\x03\x00" + chan.to_bytes(1, 'little') + timestamp + msg.encode("utf-8")
        return await self.send(data, [EventType.OK, EventType.ERROR])
        
    async def send_other_params(self, manual_add_contacts : bool, telemetry_mode_base : bool, telemetry_mode_loc : bool) :
        telemetry_mode = (telemetry_mode_base & 0b11) | ((telemetry_mode_loc & 0b11) << 2)
        data = b"\x26" + manual_add_contacts.to_bytes(1) + telemetry_mode.to_bytes(1) 
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def send_telemetry_req(self, dst: DestinationType) -> Event :
        dst_bytes = _validate_destination(dst, prefix_length=32)
        logger.debug(f"Asking telemetry to {dst_bytes.hex()}")

        data = b"\x27\x00\x00\x00" + dst_bytes
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

    async def get_custom_vars(self) -> Event:
        logger.debug(f"Asking for custom vars")
        data = b"\x28"
        return await self.send(data, [EventType.CUSTOM_VARS, EventType.ERROR])

    async def set_custom_var(self, key, value) -> Event:
        logger.debug(f"Setting custom var {key} to {value}")
        data = b"\x29" + key.encode("utf-8") + b":" + value.encode("utf-8")
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def send_cli(self, cmd) -> Event:
        logger.debug(f"Sending CLI command: {cmd}")
        data = b"\x32" + cmd.encode('utf-8')
        return await self.send(data, [EventType.CLI_RESPONSE, EventType.ERROR])
        
    async def send_trace(self, auth_code: int = 0, tag: Optional[int] = None, 
                      flags: int = 0, path: Optional[Union[str, bytes, bytearray]] = None) -> Event:
        """
        Send a trace packet to test routing through specific repeaters
        
        Args:
            auth_code: 32-bit authentication code (default: 0)
            tag: 32-bit integer to identify this trace (default: random)
            flags: 8-bit flags field (default: 0)
            path: Optional string with comma-separated hex values representing repeater pubkeys (e.g. "23,5f,3a")
                 or a bytes/bytearray object with the raw path data
                 
        Returns:
            Event object with sent status, tag, and estimated timeout in milliseconds
        """
        # Generate random tag if not provided
        if tag is None:
            tag = random.randint(1, 0xFFFFFFFF)
        if auth_code is None:
            auth_code = random.randint(1, 0xFFFFFFFF)
            
        logger.debug(f"Sending trace: tag={tag}, auth={auth_code}, flags={flags}, path={path}")
        
        # Prepare the command packet: CMD(1) + tag(4) + auth_code(4) + flags(1) + [path]
        cmd_data = bytearray([36])  # CMD_SEND_TRACE_PATH
        cmd_data.extend(tag.to_bytes(4, 'little'))
        cmd_data.extend(auth_code.to_bytes(4, 'little'))
        cmd_data.append(flags)
        
        # Process path if provided
        if path:
            if isinstance(path, str):
                # Convert comma-separated hex values to bytes
                try:
                    path_bytes = bytearray()
                    for hex_val in path.split(','):
                        hex_val = hex_val.strip()
                        path_bytes.append(int(hex_val, 16))
                    cmd_data.extend(path_bytes)
                except ValueError as e:
                    logger.error(f"Invalid path format: {e}")
                    return Event(EventType.ERROR, {"reason": "invalid_path_format"})
            elif isinstance(path, (bytes, bytearray)):
                cmd_data.extend(path)
            else:
                logger.error(f"Unsupported path type: {type(path)}")
                return Event(EventType.ERROR, {"reason": "unsupported_path_type"})
        
        return await self.send(cmd_data, [EventType.MSG_SENT, EventType.ERROR])
