#!/usr/bin/python

import asyncio

from meshcore import MeshCore
from meshcore import BLEConnection

ADDRESS = "t1000"

async def main () :
    con  = BLEConnection(ADDRESS)
    await con.connect()
    mc = MeshCore(con)
    await mc.connect()

    print(mc.self_info)

asyncio.run(main())
