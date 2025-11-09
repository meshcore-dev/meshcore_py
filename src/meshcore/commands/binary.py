import logging

from .base import CommandHandlerBase
from ..events import EventType
from ..packets import BinaryReqType
import struct, secrets

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

    async def req_neighbors_sync(self, contact, count=10):
        data = (
            bytes([0,               # request_version = 0
                count]) +
            struct.pack("<H", 0) +  # offset = 0 (LE)
            bytes([0,               # order_by = 0 (newest->oldest)
                6]) +               # pubkey_prefix_length = 6 Bytes
            secrets.token_bytes(4)  # 4-Byte random value
        )

        res = await self.send_binary_req(
            dst=contact,
            request_type=BinaryReqType.NEIGHBORS,
            data=data,
            timeout=15
        )
        if res.type == EventType.ERROR:
            return None

        if self.dispatcher is None:
            return None
        
        # Listen for BINARY_RESPONSE event
        telem_event = await self.dispatcher.wait_for_event(
            EventType.BINARY_RESPONSE,
            attribute_filters={"tag": res.payload["expected_ack"].hex()},
            timeout=15,
        )
        if telem_event is None:
            return None
        data = bytes.fromhex(telem_event.payload["data"])
        neighbours_count, results_count = struct.unpack_from("<HH", data, 0)
        off = 4
        esize = 11

        out = []
        for _ in range(results_count):
            if off + 11 > len(data):
                break
            prefix = data[off:off+6].hex(); off += 6
            heard = struct.unpack_from("<I", data, off)[0]; off += 4
            snr_raw = struct.unpack_from("b", data, off)[0]; off += 1
            snr = snr_raw / 4.0          # <-- ¼-dB resolution
            out.append((prefix, heard, snr))
        
        return out

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
