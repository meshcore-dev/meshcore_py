#!/usr/bin/env python3
"""
Example: Sign arbitrary data with a MeshCore device over BLE.

The device performs signing on its private key via the CMD_SIGN_* flow:
- sign_start(): initializes a signing session and returns max buffer size (8KB on firmware)
- sign_data(): streams one or more data chunks
- sign_finish(): returns the signature
"""

import argparse
import asyncio
from pathlib import Path
import sys
from textwrap import wrap

# Ensure local src/ is on path when running from repo root
repo_root = Path(__file__).resolve().parents[1]
src_path = repo_root / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

from meshcore import MeshCore, EventType


async def main():
    parser = argparse.ArgumentParser(
        description="Sign data using a MeshCore device over BLE"
    )
    parser.add_argument(
        "-a",
        "--addr",
        help="BLE address of the device (optional, will scan if not provided)",
    )
    parser.add_argument(
        "-p",
        "--pin",
        help="PIN for BLE pairing (optional)",
    )
    parser.add_argument(
        "-d",
        "--data",
        default="Hello from meshcore_py!",
        help="ASCII data to sign (will be UTF-8 encoded)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="Chunk size to stream to the device (bytes)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    meshcore = None
    try:
        print("Connecting to MeshCore device...")
        meshcore = await MeshCore.create_ble(address=args.addr, pin=args.pin, debug=args.debug)
        print("✅ Connected.")

        data_bytes = args.data.encode("utf-8")
        sig_evt = await meshcore.commands.sign(data_bytes, chunk_size=max(1, args.chunk_size))
        if sig_evt.type == EventType.ERROR:
            raise RuntimeError(f"sign failed: {sig_evt.payload}")
        signature = sig_evt.payload.get("signature", b"")
        print(f"Signature ({len(signature)} bytes):")
        # Pretty-print hex in 32-byte lines
        hex_sig = signature.hex()
        for line in wrap(hex_sig, 64):
            print(line)

        print("\nSigning flow completed!")

    except ConnectionError as e:
        print(f"❌ Failed to connect: {e}")
        return 1
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    finally:
        if meshcore:
            await meshcore.disconnect()
            print("Disconnected.")


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)

