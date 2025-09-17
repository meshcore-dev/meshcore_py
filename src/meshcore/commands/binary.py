import logging

from .base import CommandHandlerBase
from ..events import EventType
from ..packets import BinaryReqType

logger = logging.getLogger("meshcore")


class BinaryCommandHandler(CommandHandlerBase):
    """Helper functions to handle binary requests through binary commands"""

    async def req_status(self, contact, timeout=0, min_timeout=0):
        logger.error("*** please consider using req_status_sync instead of req_status") 
        return await self.req_status_sync(contact, timeout, min_timeout)

    async def req_status_sync(self, contact, timeout=0, min_timeout=0):
        res = await self.send_binary_req(
            contact,
            BinaryReqType.STATUS,
            timeout=timeout,
            min_timeout=min_timeout
        )
        if res.type == EventType.ERROR:
            return None
            
        exp_tag = res.payload["expected_ack"].hex()
        timeout = res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
        timeout = timeout if min_timeout < timeout else min_timeout
        
        if self.dispatcher is None:
            return None
            
        status_event = await self.dispatcher.wait_for_event(
            EventType.STATUS_RESPONSE,
            attribute_filters={"tag": exp_tag},
            timeout=timeout,
        )
        
        return status_event.payload if status_event else None

    async def req_telemetry(self, contact, timeout=0, min_timeout=0):
        logger.error("*** please consider using req_telemetry_sync instead of req_telemetry") 
        return await self.req_telemetry_sync(contact, timeout, min_timeout)

    async def req_telemetry_sync(self, contact, timeout=0, min_timeout=0):
        res = await self.send_binary_req(
            contact,
            BinaryReqType.TELEMETRY,
            timeout=timeout,
            min_timeout=min_timeout
        )
        if res.type == EventType.ERROR:
            return None
            
        timeout = res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
        timeout = timeout if min_timeout < timeout else min_timeout

        if self.dispatcher is None:
            return None
            
        # Listen for TELEMETRY_RESPONSE event
        telem_event = await self.dispatcher.wait_for_event(
            EventType.TELEMETRY_RESPONSE,
            attribute_filters={"tag": res.payload["expected_ack"].hex()},
            timeout=timeout,
        )
        
        return telem_event.payload["lpp"] if telem_event else None

    async def req_mma(self, contact, timeout=0, min_timeout=0):
        logger.error("*** please consider using req_mma_sync instead of req_mma") 
        return await self.req_mma_sync(contact, start, end, timeout,min_timeout)

    async def req_mma_sync(self, contact, start, end, timeout=0,min_timeout=0):
        req = (
            start.to_bytes(4, "little", signed=False)
            + end.to_bytes(4, "little", signed=False)
            + b"\0\0"
        )
        res = await self.send_binary_req(
            contact,
            BinaryReqType.MMA,
            data=req,
            timeout=timeout
        )
        if res.type == EventType.ERROR:
            return None
            
        timeout = res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
        timeout = timeout if min_timeout < timeout else min_timeout
        
        if self.dispatcher is None:
            return None
            
        # Listen for MMA_RESPONSE
        mma_event = await self.dispatcher.wait_for_event(
            EventType.MMA_RESPONSE,
            attribute_filters={"tag": res.payload["expected_ack"].hex()},
            timeout=timeout,
        )
        
        return mma_event.payload["mma_data"] if mma_event else None

    async def req_acl(self, contact, timeout=0, min_timeout=0):
        logger.error("*** please consider using req_acl_sync instead of req_acl") 
        return await self.req_acl_sync(contact, timeout, min_timeout)

    async def req_acl_sync(self, contact, timeout=0, min_timeout=0):
        req = b"\0\0"
        res = await self.send_binary_req(
            contact,
            BinaryReqType.ACL,
            data=req,
            timeout=timeout
        )
        if res.type == EventType.ERROR:
            return None
            
        timeout = res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
        timeout = timeout if timeout > min_timeout else min_timeout
        
        if self.dispatcher is None:
            return None
            
        # Listen for ACL_RESPONSE event with matching tag
        acl_event = await self.dispatcher.wait_for_event(
            EventType.ACL_RESPONSE,
            attribute_filters={"tag": res.payload["expected_ack"].hex()},
            timeout=timeout,
        )
        
        return acl_event.payload["acl_data"] if acl_event else None
