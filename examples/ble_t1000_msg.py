#!/usr/bin/python

import asyncio
import json
from meshcore import MeshCore
from meshcore import BLEConnection

ADDRESS = "t1000" # node ble adress or name
DEST = "mchome"
MSG = "Hello World"

async def main () :
    con  = BLEConnection(ADDRESS)
    await con.connect()
    mc = MeshCore(con)
    await mc.connect()

    await mc.ensure_contacts()
    await mc.send_msg(bytes.fromhex(mc.contacts[DEST]["public_key"])[0:6],MSG)

asyncio.run(main())
