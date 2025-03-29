#!/usr/bin/python
DISPLAYNAME="Center at MC node location"

from meshcore import BLEConnection
from meshcore import MeshCore
import asyncio

ADDRESS = "t1000"

async def main () :
    con  = BLEConnection(ADDRESS)
    await con.connect()
    mc = MeshCore(con)
    await mc.connect()

    infos = mc.self_info

    lat=infos["adv_lat"]
    lon=infos["adv_lon"]

    print('[{"cmd":"prefset_n","args":{"pref":"lat","value":' + str(lat) + '}},')
    print('{"cmd":"prefset_n","args":{"pref":"lon","value":' + str(lon) + '}}]')

asyncio.run(main())
