"""Tests for reconnect-path fixes (F01, F02, F03, N11)."""

import asyncio

import pytest

from meshcore.connection_manager import ConnectionManager
from meshcore.events import Event, EventDispatcher, EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeConnection:
    """Minimal stub that satisfies ConnectionProtocol."""

    def __init__(self, connect_results=None):
        """
        Args:
            connect_results: iterator of return values for successive
                connect() calls.  ``None`` means soft failure; a string
                means success; raising is also supported via sentinel.
        """
        self._connect_results = list(connect_results or ["ok"])
        self._call_index = 0
        self.reader = None

    async def connect(self):
        if self._call_index < len(self._connect_results):
            result = self._connect_results[self._call_index]
            self._call_index += 1
        else:
            result = self._connect_results[-1]
        if isinstance(result, Exception):
            raise result
        return result

    async def disconnect(self):
        pass

    async def send(self, data):
        pass

    def set_reader(self, reader):
        self.reader = reader


class RaisingConnection(FakeConnection):
    """Connection that raises on every connect() attempt."""

    def __init__(self, exc=None):
        super().__init__()
        self._exc = exc or ConnectionError("boom")

    async def connect(self):
        raise self._exc


class _EventCollector:
    """Subscribes to all events and records them."""

    def __init__(self, dispatcher: EventDispatcher):
        self.events: list[Event] = []
        dispatcher.subscribe(None, self._on_event)

    async def _on_event(self, event: Event):
        self.events.append(event)


# ---------------------------------------------------------------------------
# F01 — TCP connect() should return a plain value, not an asyncio.Future
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tcp_connect_returns_plain_string():
    """F01: After the fix, TCPConnection.connect() returns self.host (a
    plain string), not an asyncio.Future.  We test indirectly via
    ConnectionManager — the CONNECTED event payload should contain a plain
    string, not a Future object."""
    conn = FakeConnection(connect_results=["10.0.0.1"])
    dispatcher = EventDispatcher()
    await dispatcher.start()
    try:
        collector = _EventCollector(dispatcher)
        mgr = ConnectionManager(conn, dispatcher)

        result = await mgr.connect()

        assert result == "10.0.0.1"
        # Give the dispatcher a moment to deliver the event
        await asyncio.sleep(0.05)
        connected_events = [e for e in collector.events if e.type == EventType.CONNECTED]
        assert len(connected_events) == 1
        payload = connected_events[0].payload
        assert payload["connection_info"] == "10.0.0.1"
        # The payload value must NOT be an asyncio.Future
        assert not isinstance(payload["connection_info"], asyncio.Future)
    finally:
        await dispatcher.stop()


# ---------------------------------------------------------------------------
# F03 — Reconnect attempts must not compound (no tail-recursive create_task)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconnect_loop_does_not_compound():
    """F03: _attempt_reconnect must use a single iterative loop.  After
    max_reconnect_attempts failures, exactly that many connect() calls
    should have been made — no exponential fan-out from orphaned tasks."""
    # All attempts fail (return None)
    conn = FakeConnection(connect_results=[None, None, None, None])
    dispatcher = EventDispatcher()
    await dispatcher.start()
    try:
        collector = _EventCollector(dispatcher)
        mgr = ConnectionManager(
            conn, dispatcher, auto_reconnect=True, max_reconnect_attempts=3,
        )
        mgr._is_connected = True  # simulate a live connection

        await mgr.handle_disconnect("test_disconnect")
        # Wait for the reconnect loop to exhaust all attempts
        # (3 attempts × 1s sleep each, but we can just await the task)
        if mgr._reconnect_task:
            await mgr._reconnect_task

        # Exactly 3 connect() calls should have been made
        assert conn._call_index == 3

        # A DISCONNECTED event with max_attempts_exceeded should have fired
        await asyncio.sleep(0.05)
        disconnected = [e for e in collector.events if e.type == EventType.DISCONNECTED]
        assert len(disconnected) == 1
        assert disconnected[0].payload.get("max_attempts_exceeded") is True
    finally:
        await dispatcher.stop()


@pytest.mark.asyncio
async def test_disconnect_cancels_reconnect_loop():
    """F03: disconnect() during an active reconnect loop must cancel the
    single task cleanly — no orphaned tasks left running."""
    # Simulate a connection that always fails (returns None), giving us
    # time to call disconnect() mid-loop.
    conn = FakeConnection(connect_results=[None, None, None, None, None])
    dispatcher = EventDispatcher()
    await dispatcher.start()
    try:
        mgr = ConnectionManager(
            conn, dispatcher, auto_reconnect=True, max_reconnect_attempts=5,
        )
        mgr._is_connected = True

        await mgr.handle_disconnect("test_disconnect")

        # Let the first attempt start (wait just past the 1s sleep)
        await asyncio.sleep(1.2)
        assert conn._call_index >= 1  # at least one attempt made

        # Now disconnect — should cancel the loop
        await mgr.disconnect()

        assert mgr._reconnect_task is None
        calls_at_cancel = conn._call_index

        # Wait a bit and confirm no more attempts happened
        await asyncio.sleep(2)
        assert conn._call_index == calls_at_cancel
    finally:
        await dispatcher.stop()


# ---------------------------------------------------------------------------
# F02 — reconnect_callback (send_appstart) is called after reconnect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconnect_callback_called_after_reconnect():
    """F02: When ConnectionManager reconnects successfully, the
    reconnect_callback (e.g. send_appstart) must be invoked."""
    callback_called = []

    async def fake_appstart():
        callback_called.append(True)

    # First connect() fails (None), second succeeds
    conn = FakeConnection(connect_results=[None, "10.0.0.1"])
    dispatcher = EventDispatcher()
    await dispatcher.start()
    try:
        mgr = ConnectionManager(
            conn, dispatcher,
            auto_reconnect=True,
            max_reconnect_attempts=3,
            reconnect_callback=fake_appstart,
        )
        mgr._is_connected = True

        await mgr.handle_disconnect("test_disconnect")
        if mgr._reconnect_task:
            await mgr._reconnect_task

        assert len(callback_called) == 1
    finally:
        await dispatcher.stop()


@pytest.mark.asyncio
async def test_reconnect_callback_failure_does_not_crash_loop():
    """F02: If the reconnect_callback raises, the reconnect still counts
    as successful (transport is up) — the callback failure is logged but
    does not crash the loop or leave the manager in a broken state."""
    async def failing_callback():
        raise RuntimeError("appstart failed")

    # connect() succeeds on first attempt
    conn = FakeConnection(connect_results=["10.0.0.1"])
    dispatcher = EventDispatcher()
    await dispatcher.start()
    try:
        collector = _EventCollector(dispatcher)
        mgr = ConnectionManager(
            conn, dispatcher,
            auto_reconnect=True,
            max_reconnect_attempts=3,
            reconnect_callback=failing_callback,
        )
        mgr._is_connected = True

        await mgr.handle_disconnect("test_disconnect")
        if mgr._reconnect_task:
            await mgr._reconnect_task

        # Despite callback failure, CONNECTED event should have fired
        await asyncio.sleep(0.05)
        connected = [e for e in collector.events if e.type == EventType.CONNECTED]
        assert len(connected) == 1
        assert mgr._is_connected is True
    finally:
        await dispatcher.stop()


# ---------------------------------------------------------------------------
# N11 — connect() returning None is a soft failure (BLE scan miss)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_none_is_soft_failure():
    """N11: When connect() returns None (e.g. BLE scan found no device),
    ConnectionManager.connect() should NOT set _is_connected and should
    NOT emit a CONNECTED event."""
    conn = FakeConnection(connect_results=[None])
    dispatcher = EventDispatcher()
    await dispatcher.start()
    try:
        collector = _EventCollector(dispatcher)
        mgr = ConnectionManager(conn, dispatcher)

        result = await mgr.connect()

        assert result is None
        assert mgr._is_connected is False
        await asyncio.sleep(0.05)
        connected = [e for e in collector.events if e.type == EventType.CONNECTED]
        assert len(connected) == 0
    finally:
        await dispatcher.stop()


@pytest.mark.asyncio
async def test_no_reconnect_callback_is_noop():
    """N11/F02: When no reconnect_callback is provided (backwards compat
    for direct ConnectionManager users), reconnect should still work."""
    conn = FakeConnection(connect_results=["10.0.0.1"])
    dispatcher = EventDispatcher()
    await dispatcher.start()
    try:
        mgr = ConnectionManager(
            conn, dispatcher,
            auto_reconnect=True,
            max_reconnect_attempts=3,
            # No reconnect_callback — default None
        )
        mgr._is_connected = True

        await mgr.handle_disconnect("test_disconnect")
        if mgr._reconnect_task:
            await mgr._reconnect_task

        assert mgr._is_connected is True
    finally:
        await dispatcher.stop()
