"""send_msg_with_retry against a fake companion radio and a real dispatcher.

The fake radio mirrors the firmware: each attempt gets its own expected ack
(sha256 over timestamp, attempt & 3 and text) and a suggested timeout, and
the ack for an attempt is pushed after a per-attempt delay.
"""
import asyncio
import time
from hashlib import sha256

import pytest
import pytest_asyncio

from meshcore.commands import CommandHandler
from meshcore.events import Event, EventDispatcher, EventType

pytestmark = pytest.mark.asyncio

PUBKEY = bytes(range(32))


class FakeRadio:
    def __init__(self, dispatcher, *, direct_timeout_ms=100, flood_timeout_ms=100,
                 ack_delays=None, ack_with_msg_sent=False):
        self.dispatcher = dispatcher
        self.direct_timeout_ms = direct_timeout_ms
        self.flood_timeout_ms = flood_timeout_ms
        # attempt -> seconds until its ack, missing = never acked
        self.ack_delays = ack_delays or {}
        self.ack_with_msg_sent = ack_with_msg_sent
        self.flood = False
        self.frames = []
        self.tasks = []

    async def send(self, data):
        data = bytes(data)
        if data[0] == 0x0D:  # reset_path
            self.flood = True
            await self.dispatcher.dispatch(Event(EventType.OK, {}))
            return
        assert data[:2] == b"\x02\x00"
        self.frames.append(data)
        attempt, ts, text = data[2], data[3:7], data[13:]
        ack = sha256(ts + bytes([attempt & 3]) + text + PUBKEY).digest()[:4]
        est = self.flood_timeout_ms if self.flood else self.direct_timeout_ms
        await self.dispatcher.dispatch(Event(
            EventType.MSG_SENT,
            {"type": int(self.flood), "expected_ack": ack, "suggested_timeout": est},
        ))
        ack_event = Event(EventType.ACK, {"code": ack.hex()}, {"code": ack.hex()})
        if self.ack_with_msg_sent:
            # both frames already queued when the caller resumes
            await self.dispatcher.dispatch(ack_event)
        elif attempt in self.ack_delays:
            async def push():
                await asyncio.sleep(self.ack_delays[attempt])
                await self.dispatcher.dispatch(ack_event)
            self.tasks.append(asyncio.create_task(push()))

    def attempts(self):
        return [f[2] for f in self.frames]

    def timestamps(self):
        return {f[3:7] for f in self.frames}


@pytest_asyncio.fixture
async def dispatcher():
    d = EventDispatcher()
    await d.start()
    yield d
    await d.stop()


def make_handler(dispatcher, radio, out_path_len=0):
    handler = CommandHandler()
    handler.set_dispatcher(dispatcher)
    handler._sender_func = radio.send
    contact = {"public_key": PUBKEY.hex(), "out_path_len": out_path_len, "out_path": ""}
    handler._get_contact_by_prefix = lambda prefix: contact
    radio.flood = out_path_len == -1
    return handler, contact


def ack_subscriptions(dispatcher):
    return [s for s in dispatcher.subscriptions if s.event_type == EventType.ACK]


async def test_ack_queued_behind_msg_sent_is_not_lost(dispatcher):
    radio = FakeRadio(dispatcher, ack_with_msg_sent=True)
    handler, contact = make_handler(dispatcher, radio)

    result = await handler.send_msg_with_retry(contact, "hello")

    assert result is not None and result.type == EventType.MSG_SENT
    assert radio.attempts() == [0]


async def test_late_ack_for_earlier_attempt_counts(dispatcher):
    # window is 0.12s, attempt 0 is acked at 0.2s while attempt 1 is pending
    radio = FakeRadio(dispatcher, ack_delays={0: 0.2})
    handler, contact = make_handler(dispatcher, radio)

    result = await handler.send_msg_with_retry(contact, "hello")

    assert result is not None
    assert radio.attempts() == [0, 1]
    first_ack = sha256(radio.frames[0][3:7] + b"\x00" + b"hello" + PUBKEY).digest()[:4]
    assert result.payload["expected_ack"] == first_ack


async def test_flood_attempt_uses_its_own_timeout(dispatcher):
    # direct path is dead; the flood after the path reset is acked at 0.3s,
    # past the direct window (0.12s) but inside the flood one (0.6s)
    radio = FakeRadio(dispatcher, direct_timeout_ms=100, flood_timeout_ms=500,
                      ack_delays={2: 0.3})
    handler, contact = make_handler(dispatcher, radio)

    result = await handler.send_msg_with_retry(contact, "hello")

    assert result is not None
    assert radio.attempts() == [0, 1, 2]
    assert radio.flood and contact["out_path_len"] == -1


async def test_explicit_timeout_applies_to_every_attempt(dispatcher):
    radio = FakeRadio(dispatcher, direct_timeout_ms=100, flood_timeout_ms=5000)
    handler, contact = make_handler(dispatcher, radio)

    start = time.monotonic()
    result = await handler.send_msg_with_retry(contact, "hello", timeout=0.05)

    assert result is None
    assert radio.attempts() == [0, 1, 2]
    assert time.monotonic() - start < 1


async def test_attempts_share_one_timestamp(dispatcher, monkeypatch):
    clock = iter(range(1_700_000_000, 1_700_000_100))
    monkeypatch.setattr(time, "time", lambda: next(clock))
    radio = FakeRadio(dispatcher)
    handler, contact = make_handler(dispatcher, radio)

    result = await handler.send_msg_with_retry(contact, "hello")

    assert result is None
    assert radio.attempts() == [0, 1, 2]
    assert len(radio.timestamps()) == 1


async def test_caller_timestamp_is_kept(dispatcher):
    radio = FakeRadio(dispatcher, ack_delays={0: 0.01})
    handler, contact = make_handler(dispatcher, radio)

    await handler.send_msg_with_retry(contact, "hello", timestamp=1234)

    assert radio.timestamps() == {(1234).to_bytes(4, "little")}


async def test_flood_contact_stops_at_max_flood_attempts(dispatcher):
    radio = FakeRadio(dispatcher)
    handler, contact = make_handler(dispatcher, radio, out_path_len=-1)

    result = await handler.send_msg_with_retry(contact, "hello")

    assert result is None
    assert radio.attempts() == [0, 1]


async def test_unrelated_ack_is_ignored(dispatcher):
    radio = FakeRadio(dispatcher)
    handler, contact = make_handler(dispatcher, radio)

    async def stray_ack():
        await asyncio.sleep(0.05)
        await dispatcher.dispatch(Event(EventType.ACK, {"code": "deadbeef"}, {"code": "deadbeef"}))

    stray = asyncio.create_task(stray_ack())
    result = await handler.send_msg_with_retry(contact, "hello", max_attempts=1)
    await stray

    assert result is None


async def test_ack_subscription_is_removed(dispatcher):
    radio = FakeRadio(dispatcher, ack_delays={0: 0.01})
    handler, contact = make_handler(dispatcher, radio)

    assert await handler.send_msg_with_retry(contact, "hello") is not None
    assert ack_subscriptions(dispatcher) == []

    radio.ack_delays = {}
    assert await handler.send_msg_with_retry(contact, "hello") is None
    assert ack_subscriptions(dispatcher) == []
