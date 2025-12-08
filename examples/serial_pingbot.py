import asyncio
from meshcore import MeshCore, EventType

SERIAL_PORT = "COM16" # change this to your serial port, tested with T1000-E
CHANNEL_IDX = 1  # change this to the index of your "#ping" channel


async def main():
    # Connect to the MeshCore companion over serial
    meshcore = await MeshCore.create_serial(SERIAL_PORT, debug=True)
    print(f"Connected on {SERIAL_PORT}")

    # Let the library automatically fetch messages from the device
    await meshcore.start_auto_message_fetching()

    async def handle_channel_message(event):
        msg = event.payload

        chan = msg.get("channel_idx")
        text = msg.get("text", "")
        path_len = msg.get("path_len")
        sender = text.split(":", 1)[0].strip()

        print(f"Received on channel {chan} from {sender}: {text} | path_len={path_len}")

        if chan == CHANNEL_IDX and "ping" in text.lower():

            reply = f"@[{sender}] Pong 🏓({path_len})"

            print(f"Detected Ping. Replying in channel {CHANNEL_IDX} with:\n{reply}")

            result = await meshcore.commands.send_chan_msg(CHANNEL_IDX, reply)

            if result.type == EventType.ERROR:
                print(f"Error sending reply: {result.payload}")
            else:
                print("Reply sent")


    # Subscribe only to messages from the chosen channel
    subscription = meshcore.subscribe(
        EventType.CHANNEL_MSG_RECV,
        handle_channel_message,
        attribute_filters={"channel_idx": CHANNEL_IDX},
    )

    try:
        print(f"Listening for 'Ping' on channel {CHANNEL_IDX}...")
        # Keep the program alive
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("Stopping listener...")
    finally:
        meshcore.unsubscribe(subscription)
        await meshcore.stop_auto_message_fetching()
        await meshcore.disconnect()
        print("Disconnected")


if __name__ == "__main__":
    asyncio.run(main())
