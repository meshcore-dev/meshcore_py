#!/usr/bin/python

import asyncio

from meshcore import MeshCore
from meshcore import SerialConnection

PORT = "/dev/ttyUSB0"
BAUDRATE = 115200

async def main () :
    con  = SerialConnection(PORT, BAUDRATE)
    await con.connect()
    await asyncio.sleep(0.1) # time for transport to establish    

    mc = MeshCore(con)
    await mc.connect()

    print(mc.self_info)

asyncio.run(main())
