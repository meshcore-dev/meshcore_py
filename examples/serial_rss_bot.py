import asyncio
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
import hashlib


from meshcore import MeshCore, EventType

# =====================
# Config
# =====================
SERIAL_PORT = "COM4"          # change this to your serial port
CHANNEL_IDXS = [6]#[5, 6]         # change this to the index of your target channel

RSS_URL = "https://data.emergency.vic.gov.au/Show?pageId=getIncidentRSS"
POLL_INTERVAL_SEC = 300       # poll interval (seconds)

# Only send items whose description (plain text) contains this keyword (case-insensitive)
KEYWORDS_REQUIRED = ["BUSHFIRE"]

# Only send these fields from the RSS description
FIELDS_TO_SEND = [
    "Type",
    "Fire District",
    "Location",     
    "Latitude",
    "Longitude",    
    "Status",
    "Size",
]

BLOCKED_STATUSES = [
    "Under Control",
    "Safe",
]

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger("serial_rssbot")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def _strip_html(html: str) -> str:
    """Convert HTML-ish fragments into plain text."""
    if not html:
        return ""

    # Normalize <br> into newlines so field parsing is reliable.
    html = re.sub(r"<\s*br\s*/?\s*>", "\n", html, flags=re.IGNORECASE)

    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
        parser.close()
        text = parser.get_text()
    except Exception:
        text = re.sub(r"<[^>]+>", "\n", html)

    text = unescape(text)
    # Normalize whitespace but keep newlines as separators.
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def _fetch_rss_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "meshcore-rss-bot/1.0",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()

def extract_fields(raw_html: str) -> dict[str, str]:
    """
    Extract desired fields from the HTML description.
    We strip HTML to text with newlines, then parse lines like "Field: value".
    """
    text = _strip_html(raw_html)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    result: dict[str, str] = {}
    for ln in lines:
        m = re.match(r"^([^:]+):\s*(.*)$", ln)
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()

        # Match desired fields case-insensitively
        for wanted in FIELDS_TO_SEND:
            if key.lower() == wanted.lower():
                result[wanted] = val
                break

    return result

def _parse_rss_items(xml_bytes: bytes) -> list[dict[str, str]]:
    """Return list of items with keys: id, description, raw_description."""
    items: list[dict[str, str]] = []

    root = ET.fromstring(xml_bytes)

    # RSS 2.0: <rss><channel><item>...
    channel = root.find("channel") if root.tag.lower().endswith("rss") else root
    if channel is None:
        return items

    for it in channel.findall("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or "").strip()
        pub_date = (it.findtext("pubDate") or "").strip()

        desc_html = it.findtext("description") or ""
        desc_text = _strip_html(desc_html)

        # stable_id = (guid or link or f"{title}|{pub_date}" or desc_text).strip()

        base_id = (guid or link or f"{title}|{pub_date}").strip()

        # fingerprint only the fields you output
        fields = extract_fields(desc_html)
        parts = []
        for k in FIELDS_TO_SEND:
            v = fields.get(k, "")
            parts.append(f"{k}={v}")
        fingerprint = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]

        stable_id = f"{base_id}|{fingerprint}"


        items.append(
            {
                "id": stable_id,
                "description": desc_text,        # plain text for keyword filtering
                "raw_description": desc_html,    # original HTML-ish description
            }
        )

    return items





def build_filtered_message(item: dict[str, str]) -> str | None:
    # Keyword filter (case-insensitive) on plain text description
    desc_text_lower = (item.get("description") or "").lower()
    if not any(k.lower() in desc_text_lower for k in KEYWORDS_REQUIRED):
        return None

    fields = extract_fields(item.get("raw_description") or "")
    if not fields:
        return None
    
    status_norm = fields.get("Status", "").strip().lower()
    blocked_norm = [b.lower() for b in BLOCKED_STATUSES]

    if status_norm in blocked_norm:
        return None


    # if any(b.lower() in status for b in BLOCKED_STATUSES):
    #     return None    

    # Keep order exactly as FIELDS_TO_SEND, skip missing
    # parts = []
    # for k in FIELDS_TO_SEND:
    #     v = fields.get(k)
    #     if v:
    #         parts.append(f"{v}")

    parts = []

    lat = fields.get("Latitude")
    lon = fields.get("Longitude")

    for k in FIELDS_TO_SEND:
        if k in ("Latitude", "Longitude"):
            continue

        v = fields.get(k)
        if v:
            parts.append(v)

    # append formatted lat,lon at the end
    if lat and lon:
        parts.append(f"{lat},{lon}")


    if not parts:
        return None

    return " | ".join(parts)


async def _fetch_items_async() -> list[dict[str, str]]:
    xml_bytes = await asyncio.to_thread(_fetch_rss_bytes, RSS_URL)
    return _parse_rss_items(xml_bytes)


async def main() -> None:
    meshcore = await MeshCore.create_serial(SERIAL_PORT, debug=True)
    print(f"Connected on {SERIAL_PORT}")

    # await meshcore.start_auto_message_fetching()

    seen_ids: set[str] = set()

    # Prime seen set so we do not spam old items on startup
    try:
        initial_items = await _fetch_items_async()
        for it in initial_items:
            if it.get("id"):
                seen_ids.add(it["id"])
        _LOGGER.info("Primed %d existing RSS items as seen.", len(seen_ids))
    except Exception as ex:
        _LOGGER.warning("Failed to prime RSS items: %s", ex)

    try:
        while True:
            try:
                items = await _fetch_items_async()

                # Feeds are usually newest-first. Send unseen in chronological order.
                new_items = [it for it in items if it.get("id") and it["id"] not in seen_ids]
                for it in reversed(new_items):
                    msg_text = build_filtered_message(it)

                    # Mark as seen even if it does not match filter, so we do not re-check forever
                    seen_ids.add(it["id"])

                    if not msg_text:
                        continue

                    # _LOGGER.info("Sending filtered RSS item to channel %s", CHANNEL_IDX)
                    # result = await meshcore.commands.send_chan_msg(CHANNEL_IDX, msg_text)
                    # if result.type == EventType.ERROR:
                    #     _LOGGER.error("Error sending RSS message: %s", result.payload)
                    for ch in CHANNEL_IDXS:
                        _LOGGER.info("Sending filtered RSS item to channel %s", ch)
                        result = await meshcore.commands.send_chan_msg(ch, msg_text)
                        if result.type == EventType.ERROR:
                            _LOGGER.error("Error sending RSS message to channel %s: %s", ch, result.payload)
                        await asyncio.sleep(5)  # seconds    
                    await asyncio.sleep(5)     


            except Exception as ex:
                _LOGGER.warning("RSS poll failed: %s", ex)

            await asyncio.sleep(POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        await meshcore.stop_auto_message_fetching()
        await meshcore.disconnect()
        print("Disconnected")


if __name__ == "__main__":
    asyncio.run(main())
