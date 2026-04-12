import logging
import json
import time
import io
from typing import Any, Dict
from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA256

logger = logging.getLogger("meshcore")

PAYLOAD_TYPENAMES = ["REQ", "RESPONSE", "TEXT_MSG", "ACK", "ADVERT", "GRP_TXT", "GRP_DATA", "ANON_REQ", "PATH", "TRACE", "MULTIPART", "CONTROL"]
ROUTE_TYPENAMES = ["TC_FLOOD", "FLOOD", "DIRECT", "TC_DIRECT"]
CONTACT_TYPENAMES = ["NONE","CLI","REP","ROOM","SENS"]

class MeshcorePacketParser:
    def __init__(self):
        self.channels = [{} for _ in range(40)] # keep our own copy of channels, 40 elements by default
        self.channels_log = [] # stores the channel msg events
        self.decrypt_channels = False

    async def newChannel(self, chan):
        idx = chan['channel_idx']
        if len(self.channels) <= idx:
            self.channels.extend([{} for _ in range(1 + idx - len(self.channels))])
        self.channels[idx] = chan 

    async def findLogChannelMsg(self, msg_hash):
        # search for the same packet
        return next((l for l in reversed(self.channels_log) if 'msg_hash' in l and l['msg_hash'] == msg_hash), None)

    async def findLogChannelPkt(self, pkt_hash):
        # search for the same packet
        return next((l for l in reversed(self.channels_log) if 'pkt_hash' in l and l['pkt_hash'] == pkt_hash), None)

    async def parsePacketPayload(self, payload, log_data={}):
        """ Parses the payload of a log_rx packet

            Parameters :
            log_data: already gathered log_data we'll expand
            payload: payload of the packet to analyze

            Returns :
            completed log_data
        """
        # Minimum viable payload is 2 bytes (1 header + 1 path_byte) for a
        # direct route. Anything shorter is provably broken — for example,
        # the LOG_DATA branch in reader.py only requires `len(data) > 3`,
        # which means a 4-byte LOG_DATA frame produces a 1-byte payload
        # here, and `path_byte = pbuf.read(1)[0]` further down would raise
        # IndexError on the empty buffer. Populate sentinel values so the
        # caller's downstream `log_data['route_type']` etc. lookups don't
        # KeyError, then return early.
        if len(payload) < 2:
            logger.debug(f"parsePacketPayload: payload too short ({len(payload)} bytes < 2), returning sentinel log_data")
            log_data["route_type"] = -1
            log_data["route_typename"] = "UNK"
            log_data["payload_type"] = -1
            log_data["payload_typename"] = "UNK"
            log_data["payload_ver"] = 0
            log_data["path_len"] = 0
            log_data["path_hash_size"] = 1
            log_data["path"] = ""
            log_data["pkt_payload"] = b""
            log_data["pkt_hash"] = 0
            return log_data

        pbuf = io.BytesIO(payload)

        header = pbuf.read(1)[0]
        route_type = header & 0x03
        payload_type = (header & 0x3c) >> 2
        payload_ver = (header & 0xc0) >> 6

        transport_code = None
        if route_type == 0x00 or route_type == 0x03: # has transport code
            transport_code = pbuf.read(4)    # discard transport code

        path_byte = pbuf.read(1)[0]
        path_hash_size = ((path_byte & 0xC0) >> 6) + 1
        path_len = (path_byte & 0x3F)
        # here path_len is number of hops, not number of bytes

        path = pbuf.read(path_len*path_hash_size).hex() # Beware of traces where pathes are mixed

        try :
            route_typename = ROUTE_TYPENAMES[route_type]
        except IndexError:
            logger.debug(f"Unknown route type {route_type}") 
            route_typename = "UNK"

        try :
            payload_typename = PAYLOAD_TYPENAMES[payload_type]
        except IndexError:
            logger.debug(f"Unknown payload type {payload_type}")
            payload_typename = "UNK"

        pkt_payload = pbuf.read()
        pkt_hash = int.from_bytes(SHA256.new(pkt_payload).digest()[0:4], "little", signed=False)

        log_data["header"] = header
        log_data["route_type"] = route_type
        log_data["route_typename"] = route_typename
        log_data["payload_type"] = payload_type
        log_data["payload_typename"]= payload_typename

        log_data["payload_ver"] = payload_ver

        if not transport_code is None:
            log_data["transport_code"] = transport_code.hex()

        log_data["path_len"] = path_len 
        log_data["path_hash_size"] = path_hash_size
        log_data["path"] = path

        log_data["pkt_payload"] = pkt_payload
        log_data["pkt_hash"] = pkt_hash

        if not payload is None and payload_type == 0x05: # flood msg / channel
            pk_buf = io.BytesIO(pkt_payload)
            chan_hash = pk_buf.read(1).hex()
            cipher_mac = pk_buf.read(2)
            msg = pk_buf.read() # until the end of buffer

            channel = None
            for c in self.channels:
                if "channel_hash" in c and c["channel_hash"] == chan_hash : # validate against MAC
                    h = HMAC.new(c["channel_secret"], digestmod=SHA256)
                    h.update(msg)
                    if h.digest()[0:2] == cipher_mac:
                        channel = c
                        break

            log_data["chan_hash"] = chan_hash
            log_data["cipher_mac"] = cipher_mac.hex()
            log_data["crypted"] = msg.hex()

            chan_name = ""
            if not channel is None :
                chan_name = channel["channel_name"]
                log_data["chan_name"] = chan_name

            if not channel is None and self.decrypt_channels:

                logged = await self.findLogChannelPkt(pkt_hash)

                if logged is None:
                    # not found: decrypt the text and hash it
                    aes_key = channel["channel_secret"]
                    cipher = AES.new(aes_key, AES.MODE_ECB)
                    uncrypted = cipher.decrypt(msg)
                    timestamp = int.from_bytes(uncrypted[0:4], "little", signed=False)
                    attempt = uncrypted[4] & 3
                    txt_type = int.from_bytes(uncrypted[4:4], "little", signed=False) >> 2
                    message = uncrypted[5:].strip(b"\0")
                    msg_hash = int.from_bytes(SHA256.new(timestamp.to_bytes(4, "little", signed=False) + message).digest()[0:4], "little", signed=False)
                    log_data["message"] = message.decode("utf-8", "ignore")
                    log_data["msg_hash"] = msg_hash
                    log_data["sender_timestamp"] = timestamp
                    log_data["attempt"] = attempt
                    log_data["txt_type"] = txt_type
                else:
                    # found: copy
                    log_data["message"] = logged["message"]
                    log_data["msg_hash"] = logged["msg_hash"]
                    log_data["sender_timestamp"] = logged["sender_timestamp"]
                    log_data["attempt"] = logged["attempt"]
                    log_data["txt_type"] = logged["txt_type"]

            self.channels_log.append(log_data)
            if len(self.channels_log) > 100:
                del self.channels_log[:25]

        elif not payload is None and payload_type == 0x04: # Advert
            pk_buf = io.BytesIO(pkt_payload)
            adv_key = pk_buf.read(32).hex()
            adv_timestamp = int.from_bytes(pk_buf.read(4), "little", signed=False)
            signature = pk_buf.read(64).hex()
            flags = pk_buf.read(1)[0]
            adv_type = flags & 0x0F
            adv_lat = None
            adv_lon = None
            adv_feat1 = None
            adv_feat2 = None
            if flags & 0x10 > 0: #has location
                adv_lat = int.from_bytes(pk_buf.read(4), "little", signed=True)/1000000.0
                adv_lon = int.from_bytes(pk_buf.read(4), "little", signed=True)/1000000.0
            if flags & 0x20 > 0: #has feature1
                adv_feat1 = pk_buf.read(2).hex()
            if flags & 0x40 > 0: #has feature2
                adv_feat2 = pk_buf.read(2).hex()
            if flags & 0x80 > 0: #has name
                adv_name = pk_buf.read().decode("utf-8", "ignore").strip("\x00")
                log_data["adv_name"] = adv_name

            log_data["adv_key"] = adv_key
            log_data["adv_timestamp"] = adv_timestamp
            log_data["signature"] = signature
            log_data["adv_flags"] = flags
            log_data["adv_type"] = adv_type
            if not adv_lat is None :
                log_data["adv_lat"] = adv_lat
            if not adv_lon is None :
                log_data["adv_lon"] = adv_lon
            if not adv_feat1 is None:
                log_data["adv_feat1"] = adv_feat1
            if not adv_feat2 is None:
                log_data["adv_feat2"] = adv_feat2

        return log_data
