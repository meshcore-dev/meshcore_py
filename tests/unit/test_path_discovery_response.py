import pytest

from meshcore.events import EventType
from meshcore.reader import MessageReader

pytestmark = pytest.mark.asyncio


class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []

    async def dispatch(self, event):
        self.dispatched_events.append(event)


async def test_path_discovery_response_decodes_3byte_paths():
    dispatcher = MockDispatcher()
    reader = MessageReader(dispatcher)

    packet = bytearray.fromhex(
        "8d"  # PacketType.PATH_DISCOVERY_RESPONSE
        "00"  # Reserved byte
        "112233445566"  # 6-byte contact public-key prefix
        "82"  # Outbound path descriptor: mode=2 (3-byte hops), hop_count=2
        "a1a2a3b1b2b3"  # Outbound path bytes: 2 hops * 3 bytes each
        "81"  # Inbound path descriptor: mode=2 (3-byte hops), hop_count=1
        "c1c2c3"  # Inbound path bytes: 1 hop * 3 bytes
    )

    await reader.handle_rx(packet)

    matching = [e for e in dispatcher.dispatched_events if e.type == EventType.PATH_RESPONSE]
    assert len(matching) == 1

    payload = matching[0].payload
    assert payload["pubkey_pre"] == "112233445566"

    assert payload["out_path_hash_len"] == 3
    assert payload["out_path_len"] == 2
    assert payload["out_path"] == "a1a2a3b1b2b3"

    assert payload["in_path_hash_len"] == 3
    assert payload["in_path_len"] == 1
    assert payload["in_path"] == "c1c2c3"
