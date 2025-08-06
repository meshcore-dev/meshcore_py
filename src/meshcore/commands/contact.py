import logging
from typing import Optional

from ..events import Event, EventType
from .base import CommandHandlerBase, DestinationType, _validate_destination

logger = logging.getLogger("meshcore")


class ContactCommands(CommandHandlerBase):
    async def get_contacts(self, lastmod=0) -> Event:
        logger.debug("Getting contacts")
        data = b"\x04"
        if lastmod > 0:
            data = data + lastmod.to_bytes(4, "little")
        return await self.send(data, [EventType.CONTACTS, EventType.ERROR])

    async def reset_path(self, key: DestinationType) -> Event:
        key_bytes = _validate_destination(key, prefix_length=32)
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

    async def update_contact(self, contact, path=None, flags=None) -> Event:
        if path is None:
            out_path_hex = contact["out_path"]
            out_path_len = contact["out_path_len"]
        else:
            out_path_hex = path
            out_path_len = int(len(path) / 2)
            # reflect the change
            contact["out_path"] = out_path_hex
            contact["out_path_len"] = out_path_len
        out_path_hex = out_path_hex + (128 - len(out_path_hex)) * "0"

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
            + contact["type"].to_bytes(1)
            + flags.to_bytes(1)
            + out_path_len.to_bytes(1, "little", signed=True)
            + bytes.fromhex(out_path_hex)
            + bytes.fromhex(adv_name_hex)
            + contact["last_advert"].to_bytes(4, "little")
            + int(contact["adv_lat"] * 1e6).to_bytes(4, "little", signed=True)
            + int(contact["adv_lon"] * 1e6).to_bytes(4, "little", signed=True)
        )
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def add_contact(self, contact) -> Event:
        return await self.update_contact(contact)

    async def change_contact_path(self, contact, path) -> Event:
        return await self.update_contact(contact, path)

    async def change_contact_flags(self, contact, flags) -> Event:
        return await self.update_contact(contact, flags=flags)
