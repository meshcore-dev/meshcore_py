#!/usr/bin/python

import asyncio
import argparse

from meshcore import MeshCore
from meshcore.events import EventType

async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Get status from a repeater via serial connection')
    # parser.add_argument('-p', '--port', required=True, help='Serial port')
    # parser.add_argument('-b', '--baudrate', type=int, default=115200, help='Baud rate')
    parser.add_argument('-r', '--repeater', required=True, help='Repeater name')
    parser.add_argument('-pw', '--password', required=True, help='Password for login')
    # parser.add_argument('-t', '--timeout', type=float, default=10.0, help='Timeout for responses in seconds')
    args = parser.parse_args()

    # Connect to the device
    mc = await MeshCore.create_ble("lora-py-tester")
    534463
    try:
        # Get contacts
        result = await mc.commands.get_contacts()
        print(result)
        print(mc._contacts)
        repeater = mc.get_contact_by_key_prefix(args.repeater)
        
        if repeater is None:
            print(f"Repeater '{args.repeater}' not found in contacts.")
            return
        
        # Send login request
        print(f"Logging in to repeater '{args.repeater}'...")
        login_event = await mc.commands.send_login(repeater, args.password)
        
        if login_event.type != EventType.ERROR:
            print("Login successful")
            
            # Continuously poll for telemetry every 60 seconds
            print("Starting continuous telemetry polling every 60 seconds...")
            while True:
                try:
                    # Send status request
                    print("Sending status request...")
                    await mc.commands.send_telemetry_req(repeater)
                    
                    # Wait for status response
                    telemetry_event = await mc.wait_for_event(EventType.TELEMETRY_RESPONSE, timeout=10)
                    print(telemetry_event)
                    
                    # Wait 60 seconds before next poll
                    await asyncio.sleep(60)
                    
                except Exception as e:
                    print(f"Error during telemetry poll: {e}")
                    # Wait before retrying
                    await asyncio.sleep(60)
            
        else:
            print("Login failed or timed out")
    
    finally:
        # Always disconnect properly
        await mc.disconnect()
        print("Disconnected from device")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
    except Exception as e:
        print(f"Error: {e}")
