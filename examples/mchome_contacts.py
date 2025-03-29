#!/usr/bin/python

import asyncio
import json
from meshcore import TCPConnection
from meshcore import MeshCore

HOSTNAME = "mchome"
PORT = 5000

async def main () :
    con  = TCPConnection(HOSTNAME, PORT)
    await con.connect()
    mc = MeshCore(con)
    await mc.connect()

    print(json.dumps(await mc.get_contacts(),indent=4))
asyncio.run(main())
