import asyncio
import logging
from enum import Enum
import json
from .events import Event, EventType
from cayennelpp import LppFrame, LppData
from cayennelpp.lpp_type import LppType
from meshcore.lpp_json_encoder import lpp_json_encoder, my_lpp_types

logger = logging.getLogger("meshcore")

class BinaryReqType(Enum):
    TELEMETRY = 3
    AMM = 4

def lpp_parse(buf):
    """Parse a given byte string and return as a LppFrame object."""
    i = 0
    lpp_data_list = []
    while i < len(buf) and buf[i] != 0:
        lppdata = LppData.from_bytes(buf[i:])
        lpp_data_list.append(lppdata)
        i = i + len(lppdata)

    return json.loads(json.dumps(LppFrame(lpp_data_list), default=lpp_json_encoder))

def lpp_parse_amm(buf):
    i = 0
    res = []
    while i < len(buf) and buf[i] != 0:
        chan = buf[i]
        i = i + 1
        type = buf[i]
        lpp_type = LppType.get_lpp_type(type)
        size = lpp_type.size
        i = i + 1
        min = lpp_type.decode(buf[i:i+size])
        i = i + size
        max = lpp_type.decode(buf[i:i+size])
        i = i + size
        avg = lpp_type.decode(buf[i:i+size])
        i = i + size
        res.append({"channel":chan, 
                    "type":my_lpp_types[type][0],
                    "avg":avg[0],
                    "min":min[0],
                    "max":max[0],
                    })
    return res

class BinaryCommandHandler :
    """ Helper functions to handle binary requests through binary commands """
    def __init__ (self, c):
        self.commands = c

    @property
    def dispatcher(self):
        return self.commands.dispatcher

    async def req_binary (self, contact, request) :
        res = await self.commands.send_binary_req(contact, request)
        logger.debug(res)
        if res.type == EventType.ERROR:
            logger.error(f"Error while requesting binary data")
            return None
        else:
            exp_tag = res.payload["expected_ack"].hex()
            timeout = res.payload["suggested_timeout"] / 1000
            res2 = await self.dispatcher.wait_for_event(EventType.BINARY_RESPONSE, attribute_filters={"tag": exp_tag}, timeout=timeout)
            logger.debug(res2)
            if res2 is None :
                return None
            else:
                return res2.payload

    async def req_telemetry (self, contact) :
        code = BinaryReqType.TELEMETRY
        req = code.to_bytes(1, 'little', signed=False)
        res = await self.req_binary(contact, req)
        if (res is None) :
            return None
        else:
            return lpp_parse(bytes.fromhex(res["data"]))

    async def req_amm (self, contact, start, end) :
        code = 4
        req = code.to_bytes(1, 'little', signed=False)\
            + start.to_bytes(4, 'little', signed = False)\
            + end.to_bytes(4, 'little', signed=False)\
            + b"\0\0"
        res = await self.req_binary(contact, req)
        if (res is None) :
            return None
        else:
            return lpp_parse_amm(bytes.fromhex(res["data"])[4:])
