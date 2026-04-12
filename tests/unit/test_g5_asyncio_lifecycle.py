"""
Verification tests for G5 — Asyncio lifecycle fixes (F05, F07, F08, F19).
"""

import asyncio
import gc
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from meshcore.events import Event, EventDispatcher, EventType
from meshcore.tcp_cx import TCPConnection
from meshcore.serial_cx import SerialConnection
from meshcore.commands.base import CommandHandlerBase


class TestF05BackgroundTaskTracking(unittest.TestCase):
    """F05: fire-and-forget create_task calls must be tracked to prevent GC."""

    def test_tcp_spawn_background_retains_task(self):
        """TCP _spawn_background adds the task to _background_tasks."""
        async def _run():
            cx = TCPConnection("127.0.0.1", 5555)
            completed = asyncio.Event()

            async def dummy():
                completed.set()

            task = cx._spawn_background(dummy())
            assert task in cx._background_tasks
            await completed.wait()
            # After completion, done_callback should have discarded it
            await asyncio.sleep(0)  # let done callback fire
            assert task not in cx._background_tasks

        asyncio.run(_run())

    def test_serial_spawn_background_retains_task(self):
        """Serial _spawn_background adds the task to _background_tasks."""
        async def _run():
            with patch("meshcore.serial_cx.asyncio.Event") as mock_event:
                mock_event.return_value = MagicMock()
                cx = SerialConnection("/dev/null", 115200)
            completed = asyncio.Event()

            async def dummy():
                completed.set()

            task = cx._spawn_background(dummy())
            assert task in cx._background_tasks
            await completed.wait()
            await asyncio.sleep(0)
            assert task not in cx._background_tasks

        asyncio.run(_run())

    def test_event_dispatcher_spawn_background_retains_task(self):
        """EventDispatcher _spawn_background adds task to _background_tasks."""
        async def _run():
            dispatcher = EventDispatcher()
            completed = asyncio.Event()

            async def dummy():
                completed.set()

            task = dispatcher._spawn_background(dummy())
            assert task in dispatcher._background_tasks
            await completed.wait()
            await asyncio.sleep(0)
            assert task not in dispatcher._background_tasks

        asyncio.run(_run())

    def test_tcp_handle_rx_uses_tracked_task(self):
        """TCP handle_rx dispatches reader.handle_rx via _spawn_background."""
        async def _run():
            cx = TCPConnection("127.0.0.1", 5555)
            reader = AsyncMock()
            reader.handle_rx = AsyncMock()
            cx.set_reader(reader)

            # Build a minimal valid frame: 0x3e + 2-byte LE size + payload
            payload = b"\x01\x02\x03"
            size = len(payload).to_bytes(2, "little")
            frame = b"\x3e" + size + payload

            cx.handle_rx(frame)
            # Task should be tracked
            assert len(cx._background_tasks) == 1
            # Let task complete
            await asyncio.sleep(0.05)
            reader.handle_rx.assert_awaited_once_with(payload)

        asyncio.run(_run())

    def test_tcp_connection_lost_uses_tracked_task(self):
        """TCP connection_lost dispatches disconnect callback via _spawn_background."""
        async def _run():
            cx = TCPConnection("127.0.0.1", 5555)
            callback = AsyncMock()
            cx.set_disconnect_callback(callback)

            protocol = cx.MCClientProtocol(cx)
            protocol.connection_lost(None)

            assert len(cx._background_tasks) == 1
            await asyncio.sleep(0.05)
            callback.assert_awaited_once_with("tcp_disconnect")

        asyncio.run(_run())

    def test_gc_does_not_cancel_tracked_tasks(self):
        """Tracked tasks survive GC pressure (the whole point of F05)."""
        async def _run():
            cx = TCPConnection("127.0.0.1", 5555)
            result = []

            async def slow_task():
                await asyncio.sleep(0.05)
                result.append("done")

            cx._spawn_background(slow_task())
            # Force GC — untracked tasks could be collected here
            gc.collect()
            await asyncio.sleep(0.1)
            assert result == ["done"]

        asyncio.run(_run())


class TestF07TaskDoneCorrectness(unittest.TestCase):
    """F07: EventDispatcher.stop() must wait for in-flight async callbacks."""

    def test_stop_waits_for_async_callbacks(self):
        """stop() should not return until async callbacks have completed."""
        async def _run():
            dispatcher = EventDispatcher()
            await dispatcher.start()

            callback_completed = False

            async def slow_callback(event):
                nonlocal callback_completed
                await asyncio.sleep(0.1)
                callback_completed = True

            dispatcher.subscribe(EventType.OK, slow_callback)
            await dispatcher.dispatch(Event(EventType.OK, {}))

            # Give the dispatch loop a moment to pick up the event
            await asyncio.sleep(0.02)

            # stop() should wait for slow_callback to finish
            await dispatcher.stop()
            assert callback_completed, "stop() returned before async callback completed"

        asyncio.run(_run())


class TestF08DeferredPrimitiveConstruction(unittest.TestCase):
    """F08: Queue and Lock must not bind to import-time loop."""

    def test_event_dispatcher_queue_is_none_before_start(self):
        """EventDispatcher.queue should be None until start() is called."""
        dispatcher = EventDispatcher()
        assert dispatcher.queue is None

    def test_event_dispatcher_queue_created_on_start(self):
        """start() creates the queue."""
        async def _run():
            dispatcher = EventDispatcher()
            assert dispatcher.queue is None
            await dispatcher.start()
            assert dispatcher.queue is not None
            assert isinstance(dispatcher.queue, asyncio.Queue)
            await dispatcher.stop()

        asyncio.run(_run())

    def test_event_dispatcher_dispatch_before_start_raises(self):
        """dispatch() before start() should raise RuntimeError."""
        async def _run():
            dispatcher = EventDispatcher()
            with self.assertRaises(RuntimeError):
                await dispatcher.dispatch(Event(EventType.OK, {}))

        asyncio.run(_run())

    def test_command_handler_lock_is_none_before_use(self):
        """CommandHandlerBase lock should be None until first access."""
        handler = CommandHandlerBase()
        assert handler._CommandHandlerBase__mesh_request_lock is None

    def test_command_handler_lock_created_on_access(self):
        """Accessing _mesh_request_lock creates it lazily."""
        async def _run():
            handler = CommandHandlerBase()
            lock = handler._mesh_request_lock
            assert isinstance(lock, asyncio.Lock)
            # Second access returns same instance
            assert handler._mesh_request_lock is lock

        asyncio.run(_run())


class TestF19GetRunningLoop(unittest.TestCase):
    """F19: get_event_loop() replaced with get_running_loop() in send()."""

    def test_send_uses_get_running_loop(self):
        """send() should call get_running_loop, not get_event_loop."""
        async def _run():
            handler = CommandHandlerBase()
            dispatcher = EventDispatcher()
            await dispatcher.start()
            handler.set_dispatcher(dispatcher)

            mock_sender = AsyncMock()
            handler._sender_func = mock_sender

            # Patch get_running_loop to verify it's called
            with patch("meshcore.commands.base.asyncio.get_running_loop", wraps=asyncio.get_running_loop) as mock_grl:
                # send with expected_events triggers the loop = asyncio.get_running_loop() path
                result = await handler.send(
                    b"\x01",
                    expected_events=[EventType.OK],
                    timeout=0.05,
                )
                mock_grl.assert_called()

            await dispatcher.stop()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
