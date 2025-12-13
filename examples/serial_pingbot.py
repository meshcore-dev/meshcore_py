import asyncio
import logging
from typing import Any

from meshcore import MeshCore, EventType

SERIAL_PORT = "COM4"   # change this to your serial port
CHANNEL_IDX = 1        # change this to the index of your "#ping" channel

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger("serial_pingbot")

latest_pathinfo_str = "(? hops, ?)"


def parse_rx_log_data(payload: Any) -> dict[str, Any]:
    """Parse RX_LOG event payload to extract LoRa packet details.

    Expected format (hex):
      byte0: header
      byte1: path_len
      next path_len bytes: path nodes
      next byte: channel_hash (optional)
    """
    result: dict[str, Any] = {}

    try:
        hex_str = None

        if isinstance(payload, dict):
            hex_str = payload.get("payload") or payload.get("raw_hex")
        elif isinstance(payload, (str, bytes)):
            hex_str = payload

        if not hex_str:
            return result

        if isinstance(hex_str, bytes):
            hex_str = hex_str.hex()

        hex_str = str(hex_str).lower().replace(" ", "").replace("\n", "").replace("\r", "")

        if len(hex_str) < 4:
            return result

        result["header"] = hex_str[0:2]

        try:
            path_len = int(hex_str[2:4], 16)
            result["path_len"] = path_len
        except ValueError:
            return {}

        path_start = 4
        path_end = path_start + (path_len * 2)

        if len(hex_str) < path_end:
            return {}

        path_hex = hex_str[path_start:path_end]
        result["path"] = path_hex
        result["path_nodes"] = [path_hex[i:i + 2] for i in range(0, len(path_hex), 2)]

        if len(hex_str) >= path_end + 2:
            result["channel_hash"] = hex_str[path_end:path_end + 2]

    except Exception as ex:
        _LOGGER.debug(f"Error parsing RX_LOG data: {ex}")

    return result


def format_pathinfo(parsed: dict[str, Any]) -> str:
    """Return string in format: '(<path_len> hops, <aa:bb:cc>)'."""
    path_len = parsed.get("path_len")
    nodes = parsed.get("path_nodes") or []

    if path_len is None:
        return "(? hops, ?)"
    
    if path_len == 0:
        return "(0 hops, direct)"    

    path_str = ":".join(nodes) if nodes else "?"
    return f"({path_len} hops, {path_str})"


async def main():
    global latest_pathinfo_str

    meshcore = await MeshCore.create_serial(SERIAL_PORT, debug=True)
    print(f"Connected on {SERIAL_PORT}")

    await meshcore.start_auto_message_fetching()

    async def handle_rx_log_data(event):
        global latest_pathinfo_str

        rx = event.payload or {}
        raw = rx.get("payload")  # use 'payload' (not 'raw_hex') for this parser
        if not raw:
            return

        parsed = parse_rx_log_data(raw)
        if parsed:
            latest_pathinfo_str = format_pathinfo(parsed)

    async def handle_channel_message(event):
        msg = event.payload or {}

        pathinfo = latest_pathinfo_str

        chan = msg.get("channel_idx")
        text = msg.get("text", "")
        path_len = msg.get("path_len")
        sender = text.split(":", 1)[0].strip()

        print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        print(pathinfo)
        print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        print(f"Received on channel {chan} from {sender}: {text} | path_len={path_len}")

        if chan == CHANNEL_IDX and "ping" in text.lower():
            reply = f"@[{sender}] Pong 🏓{pathinfo}"
            print(f"Detected Ping. Replying in channel {CHANNEL_IDX} with:\n{reply}")

            result = await meshcore.commands.send_chan_msg(CHANNEL_IDX, reply)
            if result.type == EventType.ERROR:
                print(f"Error sending reply: {result.payload}")
            else:
                print("Reply sent")

    sub_chan = meshcore.subscribe(
        EventType.CHANNEL_MSG_RECV,
        handle_channel_message,
        attribute_filters={"channel_idx": CHANNEL_IDX},
    )

    sub_rx = meshcore.subscribe(
        EventType.RX_LOG_DATA,
        handle_rx_log_data,
    )

    try:
        print(f"Listening for 'Ping' on channel {CHANNEL_IDX} and RX_LOG_DATA...")
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("Stopping listener...")
    finally:
        meshcore.unsubscribe(sub_chan)
        meshcore.unsubscribe(sub_rx)
        await meshcore.stop_auto_message_fetching()
        await meshcore.disconnect()
        print("Disconnected")


if __name__ == "__main__":
    asyncio.run(main())
