#!/usr/bin/python

import asyncio
from meshcore import MeshCore

PORT = "/dev/ttyUSB0"
BAUDRATE = 115200
DEST = "mchome"
MSG = "hello from serial"

async def main () :
    mc = await MeshCore.create_serial(PORT, BAUDRATE)

    await mc.ensure_contacts()
    await mc.commands.send_msg(bytes.fromhex(mc.get_contact_by_name(DEST)["public_key"])[0:6], MSG)

asyncio.run(main())

