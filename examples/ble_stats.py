#!/usr/bin/python

import asyncio
import argparse
import json
from meshcore import MeshCore, EventType

DEFAULT_ADDRESS = "MeshCore-123456789"  # Default BLE address or name

async def main():
    parser = argparse.ArgumentParser(description="Read statistics from MeshCore device via BLE")
    parser.add_argument("-a", "--address", default=DEFAULT_ADDRESS, 
                       help="BLE device address or name (default: %(default)s)")
    parser.add_argument("-p", "--pin", type=int, default=None,
                       help="PIN for BLE pairing (optional)")
    args = parser.parse_args()

    print(f"Connecting to BLE device: {args.address}")
    if args.pin:
        print(f"Using PIN pairing: {args.pin}")
        mc = await MeshCore.create_ble(args.address, pin=str(args.pin))
    else:
        mc = await MeshCore.create_ble(args.address)
    
    print("Connected successfully!\n")

    try:
        # Get core statistics
        print("Fetching core statistics...")
        result = await mc.commands.get_stats_core()
        if result.type == EventType.ERROR:
            print(f"❌ Error getting core stats: {result.payload}")
        else:
            print("📊 Core Statistics:")
            print(json.dumps(result.payload, indent=2))
        print()

        # Get radio statistics
        print("Fetching radio statistics...")
        result = await mc.commands.get_stats_radio()
        if result.type == EventType.ERROR:
            print(f"❌ Error getting radio stats: {result.payload}")
        else:
            print("📡 Radio Statistics:")
            print(json.dumps(result.payload, indent=2))
        print()

        # Get packet statistics
        print("Fetching packet statistics...")
        result = await mc.commands.get_stats_packets()
        if result.type == EventType.ERROR:
            print(f"❌ Error getting packet stats: {result.payload}")
        else:
            print("📦 Packet Statistics:")
            print(json.dumps(result.payload, indent=2))
        print()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        print("Disconnecting...")
        await mc.disconnect()
        print("Disconnected.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited cleanly")
    except Exception as e:
        print(f"Error: {e}")

