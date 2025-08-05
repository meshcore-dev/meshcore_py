import logging
from enum import Enum
import json
from .base import CommandHandlerBase
from ..events import EventType
from cayennelpp import LppFrame, LppData
from cayennelpp.lpp_type import LppType
from ..lpp_json_encoder import lpp_json_encoder, my_lpp_types, lpp_format_val

logger = logging.getLogger("meshcore")


class BinaryReqType(Enum):
    TELEMETRY = 0x03
    MMA = 0x04
    ACL = 0x05


def lpp_parse(buf):
    """Parse a given byte string and return as a LppFrame object."""
    i = 0
    lpp_data_list = []
    while i < len(buf) and buf[i] != 0:
        lppdata = LppData.from_bytes(buf[i:])
        lpp_data_list.append(lppdata)
        i = i + len(lppdata)

    return json.loads(json.dumps(LppFrame(lpp_data_list), default=lpp_json_encoder))


def lpp_parse_mma(buf):
    i = 0
    res = []
    while i < len(buf) and buf[i] != 0:
        chan = buf[i]
        i = i + 1
        type = buf[i]
        lpp_type = LppType.get_lpp_type(type)
        size = lpp_type.size
        i = i + 1
        min = lpp_format_val(lpp_type, lpp_type.decode(buf[i : i + size]))
        i = i + size
        max = lpp_format_val(lpp_type, lpp_type.decode(buf[i : i + size]))
        i = i + size
        avg = lpp_format_val(lpp_type, lpp_type.decode(buf[i : i + size]))
        i = i + size
        res.append(
            {
                "channel": chan,
                "type": my_lpp_types[type][0],
                "min": min,
                "max": max,
                "avg": avg,
            }
        )
    return res


def parse_acl(buf):
    i = 0
    res = []
    while i + 7 <= len(buf):
        key = buf[i : i + 6].hex()
        perm = buf[i + 6]
        if key != "000000000000":
            res.append({"key": key, "perm": perm})
        i = i + 7
    return res


class BinaryCommandHandler(CommandHandlerBase):
    """Helper functions to handle binary requests through binary commands"""

    async def req_binary(self, contact, request, timeout=0):
        res = await self.send_binary_req(contact, request)
        logger.debug(res)
        if res.type == EventType.ERROR:
            logger.error("Error while requesting binary data")
            return None
        else:
            exp_tag = res.payload["expected_ack"].hex()
            timeout = (
                res.payload["suggested_timeout"] / 800 if timeout == 0 else timeout
            )
            res2 = await self.dispatcher.wait_for_event(
                EventType.BINARY_RESPONSE,
                attribute_filters={"tag": exp_tag},
                timeout=timeout,
            )
            logger.debug(res2)
            if res2 is None:
                return None
            else:
                return res2.payload

    async def req_telemetry(self, contact, timeout=0):
        code = BinaryReqType.TELEMETRY.value
        req = code.to_bytes(1, "little", signed=False)
        res = await self.req_binary(contact, req, timeout)
        if res is None:
            return None
        else:
            return lpp_parse(bytes.fromhex(res["data"]))

    async def req_mma(self, contact, start, end, timeout=0):
        code = BinaryReqType.MMA.value
        req = (
            code.to_bytes(1, "little", signed=False)
            + start.to_bytes(4, "little", signed=False)
            + end.to_bytes(4, "little", signed=False)
            + b"\0\0"
        )
        res = await self.req_binary(contact, req, timeout)
        if res is None:
            return None
        else:
            return lpp_parse_mma(bytes.fromhex(res["data"])[4:])

    async def req_acl(self, contact, timeout=0):
        code = BinaryReqType.ACL.value
        req = code.to_bytes(1, "little", signed=False) + b"\0\0"
        res = await self.req_binary(contact, req, timeout)
        if res is None:
            return None
        else:
            return parse_acl(bytes.fromhex(res["data"]))
