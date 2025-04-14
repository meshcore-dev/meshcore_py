#!/usr/bin/python

import asyncio

from meshcore import MeshCore
from meshcore.events import EventType

PORT = "/dev/tty.usbserial-583A0069501"
BAUDRATE = 115200

REPEATER="Orion"
PASSWORD="floopyboopy"

async def main () :
    mc = await MeshCore.create_serial(PORT, BAUDRATE)
    await mc.commands.get_contacts()
    repeater = mc.get_contact_by_name(REPEATER)
    
    if repeater is None:
        print(f"Repeater '{REPEATER}' not found in contacts.")
        return
    await mc.commands.send_login(repeater, PASSWORD)

    print("Login sent ... awaiting")

    if await mc.wait_for_event(EventType.LOGIN_SUCCESS):
        print("Logged in success")
        await mc.commands.send_statusreq(bytes.fromhex(repeater["public_key"]))
        print("Status request sent ... awaiting")
        print(await mc.wait_for_event(EventType.STATUS_RESPONSE))
    
asyncio.run(main())
