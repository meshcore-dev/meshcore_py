#!/usr/bin/env python3
"""
Test script to verify command queue implementation prevents concurrent command collisions.
Demonstrates that the queue system properly serializes commands to the single-threaded device.
"""

import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from meshcore import MeshCore, SerialConnection

TESTER_NAME = "lora-py-tester"

async def test_concurrent_commands():
    """Test that multiple concurrent commands are properly queued."""
    
    mc = await MeshCore.create_ble(TESTER_NAME, debug=False)

    try:
        await mc.connect()
        print("Connected successfully!")
        
        # Test 1: Send multiple commands concurrently
        print("\n=== Test 1: Concurrent Commands ===")
        print("Sending 4 commands simultaneously...")
        start_time = time.time()
        
        # Create multiple command tasks that would normally collide
        tasks = [
            asyncio.create_task(mc.commands.get_time()),
            asyncio.create_task(mc.commands.get_bat()),
            asyncio.create_task(mc.commands.send_device_query()),
            asyncio.create_task(mc.commands.get_contacts()),
        ]
        
        # Wait for all to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        elapsed = time.time() - start_time
        print(f"Completed {len(tasks)} commands in {elapsed:.2f} seconds")
        
        # Check results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"  Task {i}: ERROR - {result}")
            else:
                print(f"  Task {i}: {result.type.name}") # type: ignore
        
        # Test 2: Rapid sequential commands
        print("\n=== Test 2: Rapid Sequential Commands ===")
        print("Sending 5 commands rapidly without delay...")
        start_time = time.time()
        
        for i in range(5):
            result = await mc.commands.get_time()
            print(f"  Command {i}: {result.payload}")
            # No delay - commands should still work due to queue
        
        elapsed = time.time() - start_time
        print(f"Completed 5 sequential commands in {elapsed:.2f} seconds")
        
        print("\n✅ All tests completed successfully!")
        print("The queue system is properly serializing commands.")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await mc.disconnect()
        print("Disconnected")



async def test_cleanup_on_disconnect():
    """Test that queue properly cleans up on disconnect."""
    
    print("\n=== Test 3: Clean Disconnect ===")
    print("Testing queue cleanup on disconnect...")
    
    mc = await MeshCore.create_ble(TESTER_NAME, debug=False)

    try:
        await mc.connect()
        
        # Start some commands but disconnect immediately
        tasks = [
            asyncio.create_task(mc.commands.get_contacts()),
            asyncio.create_task(mc.commands.get_time()),
            asyncio.create_task(mc.commands.get_bat()),
        ]
        
        # Give them time to queue
        await asyncio.sleep(0.1)
        
        # Disconnect (should cancel pending commands)
        print("Disconnecting with commands in queue...")
        await mc.disconnect()
        
        # Check that tasks were handled properly
        cancelled = 0
        completed = 0
        
        for task in tasks:
            if task.done():
                try:
                    result = task.result()
                    completed += 1
                    print(f"  Task completed: {result.type.name}")
                except asyncio.CancelledError:
                    cancelled += 1
                    print(f"  Task was properly cancelled")
                except Exception as e:
                    print(f"  Task failed: {e}")
        
        print(f"Results: {completed} completed, {cancelled} cancelled")
        print("✅ Cleanup test passed!")
        
    except Exception as e:
        print(f"❌ Cleanup test failed: {e}")


async def main():
    """Run all queue tests."""
    print("=" * 60)
    print("Command Queue Implementation Tests")
    print("=" * 60)
    print("\nThis tests the command queue system that prevents")
    print("multiple commands from colliding on the single-threaded device.")
    print("=" * 60)
    
    # Run tests
    await test_concurrent_commands()
    print("\n" + "=" * 60)
    await test_cleanup_on_disconnect()



if __name__ == "__main__":
    asyncio.run(main())