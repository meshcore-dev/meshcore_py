#!/usr/bin/python

import asyncio
import json
from meshcore import MeshCore
from meshcore import TCPConnection
from meshcore import EventType

HOSTNAME = "mchome"
PORT = 5000
DEST = "t114_fdl"
MSG = "Hello World"

async def main () :
    con  = TCPConnection(HOSTNAME, PORT)
    await con.connect()
    mc = MeshCore(con)
    await mc.connect()

    await mc.ensure_contacts()
    contact = mc.get_contact_by_name(DEST)
    if contact is None:
        print(f"Contact '{DEST}' not found in contacts.")
        return
    ret = await mc.commands.send_msg(contact ,MSG)
    print (ret)
    exp_ack = ret["expected_ack"].hex()
    print(await mc.wait_for_event(EventType.ACK, attribute_filters={"code": exp_ack}, timeout=5))

asyncio.run(main())
