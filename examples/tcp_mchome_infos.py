#!/usr/bin/python

import asyncio

from meshcore import MeshCore
from meshcore import TCPConnection

HOSTNAME = "mchome"
PORT = 5000

async def main () :
    con  = TCPConnection(HOSTNAME, PORT)
    await con.connect()
    mc = MeshCore(con)
    await mc.connect()

    print(mc.self_info)

asyncio.run(main())
