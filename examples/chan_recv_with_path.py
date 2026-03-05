import asyncio
from meshcore import MeshCore
from meshcore import EventType
from meshcore import BLEConnection

async def main () :
    mc = await MeshCore.create_ble("f1x")
    # this will enable channel log decryption (needed to link path with message)
    mc.set_decrypt_channel_logs = True 
    # get info for channel 0 (needed so the reader has info needed for decryption)
    await mc.commands.get_channel(0)
    await mc.start_auto_message_fetching()
    while True:
        result = await mc.wait_for_event(EventType.CHANNEL_MSG_RECV)
        if result:
           print(result)

asyncio.run(main())
