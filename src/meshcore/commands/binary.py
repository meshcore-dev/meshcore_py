import logging
from mailbox import Message

from meshcore.commands.messaging import MessagingCommands
from .base import CommandHandlerBase
from ..events import EventType
from ..binary_parsing import BinaryReqType, lpp_parse, lpp_parse_mma, parse_acl

logger = logging.getLogger("meshcore")


class BinaryCommandHandler(MessagingCommands):
    """Helper functions to handle binary requests through binary commands"""


    async def req_status(self, contact, timeout=0):
        res = await self.send_binary_req(contact, BinaryReqType.STATUS.value.to_bytes(1, "little"))
        if res.type == EventType.ERROR:
            return None
            
        exp_tag = res.payload["expected_ack"].hex()
        timeout = res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
        
        if self.dispatcher is None:
            return None
            
        # Listen for STATUS_RESPONSE event with matching pubkey
        contact_pubkey_prefix = contact["public_key"][0:12]
        status_event = await self.dispatcher.wait_for_event(
            EventType.STATUS_RESPONSE,
            attribute_filters={"pubkey_prefix": contact_pubkey_prefix},
            timeout=timeout,
        )
        
        return status_event.payload if status_event else None

    async def req_telemetry(self, contact, timeout=0):
        res = await self.send_binary_req(contact, BinaryReqType.TELEMETRY.value.to_bytes(1, "little"))
        if res.type == EventType.ERROR:
            return None
            
        timeout = res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
        
        if self.dispatcher is None:
            return None
            
        # Listen for TELEMETRY_RESPONSE event with matching pubkey
        contact_pubkey_prefix = contact["public_key"][0:12]
        telem_event = await self.dispatcher.wait_for_event(
            EventType.TELEMETRY_RESPONSE,
            attribute_filters={"pubkey_prefix": contact_pubkey_prefix},
            timeout=timeout,
        )
        
        return telem_event.payload["lpp"] if telem_event else None

    async def req_mma(self, contact, start, end, timeout=0):
        req = (
            BinaryReqType.MMA.value.to_bytes(1, "little", signed=False)
            + start.to_bytes(4, "little", signed=False)
            + end.to_bytes(4, "little", signed=False)
            + b"\0\0"
        )
        res = await self.send_binary_req(contact, req)
        if res.type == EventType.ERROR:
            return None
            
        timeout = res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
        
        if self.dispatcher is None:
            return None
            
        # Listen for MMA_RESPONSE event with matching pubkey
        contact_pubkey_prefix = contact["public_key"][0:12]
        mma_event = await self.dispatcher.wait_for_event(
            EventType.MMA_RESPONSE,
            attribute_filters={"pubkey_prefix": contact_pubkey_prefix},
            timeout=timeout,
        )
        
        return mma_event.payload["mma_data"] if mma_event else None

    async def req_acl(self, contact, timeout=0):
        req = BinaryReqType.ACL.value.to_bytes(1, "little", signed=False) + b"\0\0"
        res = await self.send_binary_req(contact, req)
        if res.type == EventType.ERROR:
            return None
            
        timeout = res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
        
        if self.dispatcher is None:
            return None
            
        # Listen for ACL_RESPONSE event with matching pubkey
        contact_pubkey_prefix = contact["public_key"][0:12]
        acl_event = await self.dispatcher.wait_for_event(
            EventType.ACL_RESPONSE,
            attribute_filters={"pubkey_prefix": contact_pubkey_prefix},
            timeout=timeout,
        )
        
        return acl_event.payload["acl_data"] if acl_event else None
