import logging
from enum import Enum
import json
from cayennelpp import LppFrame, LppData
from cayennelpp.lpp_type import LppType
from .lpp_json_encoder import lpp_json_encoder, my_lpp_types, lpp_format_val

logger = logging.getLogger("meshcore")


class BinaryReqType(Enum):
    STATUS = 0x01
    KEEP_ALIVE = 0x02
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
        if lpp_type is None:
            logger.error(f"Unknown LPP type: {type}")
            return None
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