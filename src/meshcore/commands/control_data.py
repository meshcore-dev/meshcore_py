import logging
import random

from .base import CommandHandlerBase
from ..events import EventType, Event
from ..packets import ControlType, PacketType

logger = logging.getLogger("meshcore")

# Command codes
CMD_REQUEST_ADVERT = 57  # 0x39

class ControlDataCommandHandler(CommandHandlerBase):
    """Helper functions to handle binary requests through binary commands"""

    async def send_control_data (self, control_type: int, payload: bytes) -> Event:
        data = bytearray([PacketType.SEND_CONTROL_DATA.value]) 
        data.extend(control_type.to_bytes(1, "little", signed = False)) 
        data.extend(payload)

        result = await self.send(data, [EventType.OK, EventType.ERROR])
        return result

    async def send_node_discover_req (
        self,
        filter: int,
        prefix_only: bool=True,
        tag: int=None,
        since: int=None
    ) -> Event:

        if tag is None:
            tag = random.randint(1, 0xFFFFFFFF)

        data = bytearray()
        data.extend(filter.to_bytes(1, "little", signed=False))
        data.extend(tag.to_bytes(4, "little"))
        if not since is None:
            data.extend(since.to_bytes(4, "little", signed=False))

        logger.debug(f"sending node discover req {data.hex()}")

        flags = 0
        flags = flags | 1 if prefix_only else flags

        res = await self.send_control_data(
            ControlType.NODE_DISCOVER_REQ.value|flags, data)

        if res is None:
            return None
        else:
            res.payload["tag"] = tag
            return res

    async def request_advert(self, prefix: bytes, path: bytes) -> Event:
        """
        Request advertisement from a node via pull-based system.

        Args:
            prefix: First byte of target node's public key (PATH_HASH_SIZE = 1)
            path: Path to reach the node (1-64 bytes)

        Returns:
            Event with type OK on success, ERROR on failure.
            The actual response arrives asynchronously as ADVERT_RESPONSE event.

        Raises:
            ValueError: If prefix is not 1 byte or path is empty/too long

        Example:
            # Get repeater from contacts
            contacts = (await mc.commands.get_contacts()).payload
            repeater = next(c for c in contacts.values() if c['adv_type'] == 2)

            # Extract prefix and path
            prefix = bytes.fromhex(repeater['public_key'])[:1]
            path = bytes(repeater.get('out_path', [])) or prefix

            # Send request
            result = await mc.commands.request_advert(prefix, path)
            if result.type == EventType.ERROR:
                print(f"Failed: {result.payload}")
                return

            # Wait for response
            response = await mc.wait_for_event(EventType.ADVERT_RESPONSE, timeout=30)
            if response:
                print(f"Node: {response.payload['node_name']}")
        """
        if len(prefix) != 1:
            raise ValueError("Prefix must be exactly 1 byte (PATH_HASH_SIZE)")
        if not path or len(path) > 64:
            raise ValueError("Path must be 1-64 bytes")

        cmd = bytes([CMD_REQUEST_ADVERT]) + prefix + bytes([len(path)]) + path
        return await self.send(cmd, [EventType.OK, EventType.ERROR])
