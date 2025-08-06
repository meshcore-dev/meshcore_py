import logging
import random
from typing import Optional, Union

from ..events import Event, EventType
from .base import CommandHandlerBase, DestinationType, _validate_destination

logger = logging.getLogger("meshcore")


class MessagingCommands(CommandHandlerBase):
    async def get_msg(self, timeout: Optional[float] = None) -> Event:
        logger.debug("Requesting pending messages")
        return await self.send(
            b"\x0a",
            [
                EventType.CONTACT_MSG_RECV,
                EventType.CHANNEL_MSG_RECV,
                EventType.ERROR,
                EventType.NO_MORE_MSGS,
            ],
            timeout,
        )

    async def send_login(self, dst: DestinationType, pwd: str) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        logger.debug(f"Sending login request to: {dst_bytes.hex()}")
        data = b"\x1a" + dst_bytes + pwd.encode("utf-8")
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

    async def send_logout(self, dst: DestinationType) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        data = b"\x1d" + dst_bytes
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def send_statusreq(self, dst: DestinationType) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        logger.debug(f"Sending status request to: {dst_bytes.hex()}")
        data = b"\x1b" + dst_bytes
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

    async def send_cmd(
        self, dst: DestinationType, cmd: str, timestamp: Optional[int] = None
    ) -> Event:
        dst_bytes = _validate_destination(dst)
        logger.debug(f"Sending command to {dst_bytes.hex()}: {cmd}")

        if timestamp is None:
            import time

            timestamp = int(time.time())

        data = (
            b"\x02\x01\x00"
            + timestamp.to_bytes(4, "little")
            + dst_bytes
            + cmd.encode("utf-8")
        )
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

    async def send_msg(
        self, dst: DestinationType, msg: str, timestamp: Optional[int] = None
    ) -> Event:
        dst_bytes = _validate_destination(dst)
        logger.debug(f"Sending message to {dst_bytes.hex()}: {msg}")

        if timestamp is None:
            import time

            timestamp = int(time.time())

        data = (
            b"\x02\x00\x00"
            + timestamp.to_bytes(4, "little")
            + dst_bytes
            + msg.encode("utf-8")
        )
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

    async def send_chan_msg(self, chan, msg, timestamp=None) -> Event:
        logger.debug(f"Sending channel message to channel {chan}: {msg}")

        # Default to current time if timestamp not provided
        if timestamp is None:
            import time

            timestamp = int(time.time()).to_bytes(4, "little")

        data = (
            b"\x03\x00" + chan.to_bytes(1, "little") + timestamp + msg.encode("utf-8")
        )
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def send_telemetry_req(self, dst: DestinationType) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        logger.debug(f"Asking telemetry to {dst_bytes.hex()}")
        data = b"\x27\x00\x00\x00" + dst_bytes
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

    async def send_binary_req(self, dst: DestinationType, bin_data) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        logger.debug(f"Binary request to {dst_bytes.hex()}")
        data = b"\x32" + dst_bytes + bin_data
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

    async def send_path_discovery(self, dst: DestinationType) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        logger.debug(f"Path discovery request for {dst_bytes.hex()}")
        data = b"\x34\x00" + dst_bytes
        return await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

    async def send_trace(
        self,
        auth_code: int = 0,
        tag: Optional[int] = None,
        flags: int = 0,
        path: Optional[Union[str, bytes, bytearray]] = None,
    ) -> Event:
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

        logger.debug(
            f"Sending trace: tag={tag}, auth={auth_code}, flags={flags}, path={path}"
        )

        # Prepare the command packet: CMD(1) + tag(4) + auth_code(4) + flags(1) + [path]
        cmd_data = bytearray([36])  # CMD_SEND_TRACE_PATH
        cmd_data.extend(tag.to_bytes(4, "little"))
        cmd_data.extend(auth_code.to_bytes(4, "little"))
        cmd_data.append(flags)

        # Process path if provided
        if path:
            if isinstance(path, str):
                # Convert comma-separated hex values to bytes
                try:
                    path_bytes = bytearray()
                    for hex_val in path.split(","):
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
