import logging
import asyncio
from typing import Optional

from ..events import Event, EventDispatcher, EventType
from .base import CommandHandlerBase, DestinationType, _validate_destination

logger = logging.getLogger("meshcore")


class ContactCommands(CommandHandlerBase):
    async def get_contacts_async(self, lastmod=0) :
        logger.debug("Getting contacts")
        data = b"\x04"
        if lastmod > 0:
            data = data + lastmod.to_bytes(4, "little")
        # wait first event
        await self.send(data)

    async def get_contacts(self, lastmod=0, timeout=5) -> Event:
        loop = asyncio.get_running_loop()
        result = loop.create_future()
        state = {"activity": False}
    
        def on_next(event):
            state["activity"] = True
    
        def on_end(event):
            if not result.done():
                result.set_result(event)
    
        subs = [
            self.dispatcher.subscribe(EventType.NEXT_CONTACT, on_next),
            self.dispatcher.subscribe(EventType.CONTACTS, on_end),
            self.dispatcher.subscribe(EventType.ERROR, on_end),
        ]
    
        try:
            await self.get_contacts_async(lastmod)
    
            while True:
                state["activity"] = False
                try:
                    # shield so the timeout doesn't cancel the future itself
                    return await asyncio.wait_for(asyncio.shield(result), timeout)
                except asyncio.TimeoutError:
                    if state["activity"]:
                        continue  # still receiving contacts, keep waiting
                    logger.debug("Timeout while getting contacts")
                    return Event(EventType.ERROR, {"reason": "timeout waiting for contacts"})
        finally:
            for s in subs:
                s.unsubscribe()

    async def reset_path(self, key: DestinationType) -> Event:
        key_bytes = _validate_destination(key, prefix_length=32)
        contact = self._get_contact_by_prefix(key_bytes.hex()) # need a contact for return path
        if not contact is None:
            contact["out_path_len"] = -1
            contact["out_path"] = ""
        logger.debug(f"Resetting path for contact: {key_bytes.hex()}")
        data = b"\x0d" + key_bytes
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

    async def import_contact(self, card_data) -> Event:
        data = b"\x12" + card_data
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def remove_contact(self, key: DestinationType) -> Event:
        key_bytes = _validate_destination(key, prefix_length=32)
        logger.debug(f"Removing contact: {key_bytes.hex()}")
        data = b"\x0f" + key_bytes
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def update_contact(self, contact, path=None, flags=None, path_hash_mode=None) -> Event:
        if path is None:
            out_path_hex = contact["out_path"]
            out_path_len = contact["out_path_len"]
            out_path_hash_mode = contact["out_path_hash_mode"]
        else:
            if path_hash_mode is None: # not specified when calling func
                if ":" in path: # mode specified in path string
                    path_hash_mode = int(path.split(":")[1])
                    path = path.split(":")[0].replace(":","")
                else: # use device one by default
                    # out_path_len is pre-masked (& 0x3F) in reader.py, so high bits are always 0;
                    # the actual path_hash_mode is fetched from the device query below.
                    path_hash_mode = 0
                    res = await self.send_device_query()
                    if not res is None and res.type != EventType.ERROR:
                        if "path_hash_mode" in res.payload:
                            path_hash_mode = res.payload["path_hash_mode"]
                        else:
                            path_hash_mode = 0
            else:
                if ":" in path: # remove as it has been specified in args
                    path = path.split(":")[0].replace(":","")

            path_hash_size = path_hash_mode + 1

            out_path_hex = path
            out_path_len = int(len(path) / (2 * path_hash_size))
            out_path_hash_mode = path_hash_mode

            logger.debug(f"Setting {contact['adv_name']} path to {out_path_hex} with mode {out_path_hash_mode}")

            # reflect the change
            contact["out_path_hash_mode"] = out_path_hash_mode
            contact["out_path"] = out_path_hex
            contact["out_path_len"] = out_path_len

        out_path_hex = out_path_hex + (128 - len(out_path_hex)) * "0"
        if out_path_len == -1: # path did not change and contact was flood
            out_path_len = 255 # we are signed
        else:
            out_path_len = out_path_len | (out_path_hash_mode << 6)

        if flags is None:
            flags = contact["flags"]
        else:
            # reflect the change
            contact["flags"] = flags

        adv_name_hex = contact["adv_name"].encode().hex()
        adv_name_hex = adv_name_hex + (64 - len(adv_name_hex)) * "0"
        data = (
            b"\x09"
            + bytes.fromhex(contact["public_key"])
            + contact["type"].to_bytes(1, "little")
            + flags.to_bytes(1, "little")
            + int(out_path_len).to_bytes(1, "little", signed=False)
            + bytes.fromhex(out_path_hex)
            + bytes.fromhex(adv_name_hex)
            + contact["last_advert"].to_bytes(4, "little")
            + int(contact["adv_lat"] * 1e6).to_bytes(4, "little", signed=True)
            + int(contact["adv_lon"] * 1e6).to_bytes(4, "little", signed=True)
        )
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def add_contact(self, contact) -> Event:
        return await self.update_contact(contact)

    async def change_contact_path(self, contact, path, path_hash_mode=None) -> Event:
        return await self.update_contact(contact, path, path_hash_mode=path_hash_mode)

    async def change_contact_flags(self, contact, flags) -> Event:
        return await self.update_contact(contact, flags=flags)

    async def set_autoadd_config(self, flag : int) -> Event:
        data = b"\x3A" + flag.to_bytes(1, "little", signed=False)
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def get_autoadd_config(self) -> Event:
        data = b"\x3B"
        return await self.send(data, [EventType.AUTOADD_CONFIG, EventType.ERROR])

    async def get_contact_by_key(self, pubkey: bytes) -> Event:
        """N09: Retrieve a single contact by its public key (CMD 30).

        Args:
            pubkey: 32-byte public key of the contact.

        Returns:
            Event with the contact data (same format as CONTACT/NEXT_CONTACT),
            or ERROR if not found.
        """
        if not isinstance(pubkey, (bytes, bytearray)):
            raise TypeError("pubkey must be bytes-like")
        # Truncate or pad to 32 bytes
        key_bytes = bytes(pubkey[:32])
        logger.debug(f"Getting contact by key: {key_bytes.hex()}")
        data = b"\x1e" + key_bytes
        return await self.send(data, [EventType.NEXT_CONTACT, EventType.ERROR])

    async def get_advert_path(self, key: DestinationType) -> Event:
        key_bytes = _validate_destination(key, prefix_length=32)
        logger.debug(f"getting advert path for: {key} {key_bytes.hex()}")
        data = b"\x2a\0" + key_bytes
        return await self.send(data, [EventType.ADVERT_PATH, EventType.ERROR])
