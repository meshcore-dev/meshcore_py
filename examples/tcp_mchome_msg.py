#!/usr/bin/python

import asyncio
import json
from meshcore import MeshCore
from meshcore import TCPConnection

HOSTNAME = "mchome"
PORT = 5000
DEST = "t1000"
MSG = "Hello World"

async def main () :
    con  = TCPConnection(HOSTNAME, PORT)
    await con.connect()
    mc = MeshCore(con)
    await mc.connect()

    await mc.ensure_contacts()
    await mc.commands.send_msg(bytes.fromhex(mc.get_contact_by_name(DEST)["public_key"])[0:6],MSG)

asyncio.run(main())
