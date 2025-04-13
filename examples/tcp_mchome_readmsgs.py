#!/usr/bin/python

import asyncio
import json
from meshcore import TCPConnection
from meshcore import MeshCore

HOSTNAME = "mchome"
PORT = 5000
DEST = "t1000"
MSG = "Hello World"

async def main () :
    con  = TCPConnection(HOSTNAME, PORT)
    await con.connect()
    mc = MeshCore(con)
    await mc.connect()

    res = True
    while res:
        result = await mc.commands.get_msg()
        if result.get("success") == False:
            res = False
            print("No more messages")
        print (result)

asyncio.run(main())
