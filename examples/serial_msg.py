#!/usr/bin/python

import asyncio
import json
from meshcore import MeshCore
from meshcore import SerialConnection

PORT = "/dev/ttyUSB0"
BAUDRATE = 115200
DEST = "mchome"
MSG = "hello from serial"

async def main () :
    con  = SerialConnection(PORT, BAUDRATE)
    await con.connect()
    await asyncio.sleep(0.1) # time for transport to establish    

    mc = MeshCore(con)
    await mc.connect()

    await mc.ensure_contacts()
    await mc.send_msg(bytes.fromhex(mc.contacts[DEST]["public_key"])[0:6],MSG)

asyncio.run(main())
