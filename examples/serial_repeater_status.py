#!/usr/bin/python

import asyncio

from meshcore import MeshCore
from meshcore import printerr
from meshcore import SerialConnection

PORT = "/dev/ttyUSB0"
BAUDRATE = 115200

REPEATER="FdlRoom"
PASSWORD="password"

async def main () :
    con  = SerialConnection(PORT, BAUDRATE)
    await con.connect()
    await asyncio.sleep(0.1) # time for transport to establish    

    mc = MeshCore(con)
    await mc.connect()

    contacts = await mc.get_contacts()
    repeater = contacts[REPEATER]
    await mc.send_login(bytes.fromhex(repeater["public_key"]), PASSWORD)

    printerr("Login sent ... awaiting")

    if await mc.wait_login() :
        await mc.send_statusreq(bytes.fromhex(repeater["public_key"]))
        print(await mc.wait_status())
    
asyncio.run(main())
