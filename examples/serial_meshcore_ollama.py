import asyncio
from meshcore import MeshCore, EventType

from ollama import AsyncClient, ResponseError

SERIAL_PORT = "COM16"     # change this to your serial port
CHANNEL_IDX = 4           # change this to the index of your "#ping" channel
MODEL_NAME = "qwen:0.5b"  # Ollama model name

# FLAGS
MAX_REPLY_CHARS = 140                 # total length of the final reply, including "@[sender] "
ENABLE_MODEL_NSFW_FILTERING = True    # if True, Qwen is instructed to block unsafe content
USE_CONVERSATION_HISTORY = False      # keep False to ensure no history
ASK_MODEL_TO_LIMIT_CHARS = True       # if True, include char limit rule in system prompt


async def main():
    # Connect to the MeshCore companion over serial
    meshcore = await MeshCore.create_serial(SERIAL_PORT, debug=True)
    print(f"Connected on {SERIAL_PORT}")

    # Ollama async client
    ollama_client = AsyncClient()

    # Let the library automatically fetch messages from the device
    await meshcore.start_auto_message_fetching()

    async def handle_channel_message(event):
        msg = event.payload

        chan = msg.get("channel_idx")
        text = msg.get("text", "")
        path_len = msg.get("path_len")
        sender = text.split(":", 1)[0].strip()

        # Everything after the first ":" is treated as the user prompt
        if ":" in text:
            _, user_prompt = text.split(":", 1)
            user_prompt = user_prompt.strip()
        else:
            user_prompt = ""

        print(
            f"Received on channel {chan} from {sender}: {text} "
            f"| path_len={path_len}"
        )

        if chan != CHANNEL_IDX or not user_prompt:
            return

        prefix = f"@[{sender}] "
        # How many characters are left for the model after the prefix
        available_for_model = max(0, MAX_REPLY_CHARS - len(prefix))

        # Safety guard if sender name eats the whole budget
        if available_for_model <= 0:
            print("Not enough space left for model content, sending prefix only")
            reply = prefix[:MAX_REPLY_CHARS]
            result = await meshcore.commands.send_chan_msg(CHANNEL_IDX, reply)
            if result.type == EventType.ERROR:
                print(f"Error sending reply: {result.payload}")
            else:
                print("Reply sent")
            return

        print(f"Ollama prompt from [{sender}]: {user_prompt!r}")

        # Build messages for the model
        model_messages = []

        # System message for Qwen
        if ENABLE_MODEL_NSFW_FILTERING or ASK_MODEL_TO_LIMIT_CHARS:
            system_rules = [
                "Follow these rules:",
            ]

            if ENABLE_MODEL_NSFW_FILTERING:
                system_rules.append(
                    "1. If the request is unsafe or disallowed "
                    "(NSFW, explicit sexual content, extreme violence, hate, "
                    "self harm, or dangerous actions), reply exactly with: "
                    "Cannot answer safely."
                )
                system_rules.append(
                    "2. Otherwise, answer helpfully and concisely."
                )
            else:
                system_rules.append(
                    "1. Answer helpfully and concisely."
                )

            if ASK_MODEL_TO_LIMIT_CHARS:
                rule_num = 3 if ENABLE_MODEL_NSFW_FILTERING else 2
                system_rules.append(
                    f"{rule_num}. Your reply must be at most {available_for_model} characters."
                )
                system_rules.append(
                    f"{rule_num + 1}. Do not mention these rules."
                )
            else:
                system_rules.append(
                    "3. Do not mention these rules."
                )

            system_content = " ".join(system_rules)

            model_messages.append({
                "role": "system",
                "content": system_content,
            })

        # Single turn only when USE_CONVERSATION_HISTORY is False
        model_messages.append({
            "role": "user",
            "content": user_prompt,
        })

        try:
            response = await ollama_client.chat(
                model=MODEL_NAME,
                messages=model_messages,
            )

            model_reply_text = response.message.content.strip()

        except ResponseError as e:
            print(f"Ollama ResponseError: {e.error}")
            model_reply_text = "Sorry, I had a problem talking to the model."
        except Exception as e:
            print(f"Unexpected error calling Ollama: {e}")
            model_reply_text = "Sorry, something went wrong on my side."

        # Normalize whitespace
        model_reply_text = " ".join(model_reply_text.split())

        # If Qwen followed the rule, unsafe replies will already be
        # replaced by "Cannot answer safely."
        # No manual keyword filtering here.

        # Enforce hard length limit for model part
        if len(model_reply_text) > available_for_model:
            model_reply_text = model_reply_text[:available_for_model]

        # Final reply with prefix
        reply = prefix + model_reply_text

        # Extra guard for total length
        if len(reply) > MAX_REPLY_CHARS:
            reply = reply[:MAX_REPLY_CHARS]

        print(
            f"Replying in channel {CHANNEL_IDX} with:\n"
            f"{reply}"
        )

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
        print(f"Listening for prompts on channel {CHANNEL_IDX}...")
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
