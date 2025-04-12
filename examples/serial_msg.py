#!/usr/bin/python

import asyncio
from meshcore import MeshCore

PORT = "/dev/tty.usbserial-583A0069501"
BAUDRATE = 115200
DEST = "🦄"
MSG = "hello from serial"

async def main () :
    mc = await MeshCore.create_serial(PORT, BAUDRATE)

    await mc.ensure_contacts()
    contact = mc.get_contact_by_name(DEST)
    if not contact:
        print(f"Contact {DEST} not found")
        return
    await mc.commands.send_msg(bytes.fromhex(contact["public_key"])[0:6], MSG)
    print ("Message sent ... awaiting")

asyncio.run(main())

