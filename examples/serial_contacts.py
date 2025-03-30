#!/usr/bin/python

import asyncio
import json
from meshcore import MeshCore
from meshcore import SerialConnection

PORT = "/dev/ttyUSB0"
BAUDRATE = 115200

async def main () :
    con  = SerialConnection(PORT, BAUDRATE)
    await con.connect()
    await asyncio.sleep(0.1)
    mc = MeshCore(con)
    await mc.connect()

    print(json.dumps(await mc.get_contacts(),indent=4))

asyncio.run(main())
