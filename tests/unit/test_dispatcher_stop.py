import asyncio

import pytest

from meshcore.events import Event, EventDispatcher, EventType

pytestmark = pytest.mark.asyncio


async def _stop_within(dispatcher, timeout=1.0):
    # stop() is awaited in this task, as MeshCore.disconnect() does, with a
    # timer to cancel it. asyncio.wait_for() would run it in a new task on
    # Python 3.10 and 3.11, letting the loop drain the queue before stop()
    # starts, and the hang would go unseen there.
    timer = asyncio.get_running_loop().call_later(
        timeout, asyncio.current_task().cancel
    )
    try:
        await dispatcher.stop()
    except asyncio.CancelledError:
        pytest.fail("EventDispatcher.stop() did not return")
    finally:
        timer.cancel()


async def test_stop_with_events_queued():
    """stop() drains the queue: two events queued while the loop waits in
    queue.get() are both handled, and stop() returns."""
    dispatcher = EventDispatcher()
    seen = []
    dispatcher.subscribe(EventType.OK, lambda event: seen.append(event.payload["n"]))
    await dispatcher.start()
    await asyncio.sleep(0)  # the loop now waits in queue.get()

    await dispatcher.dispatch(Event(EventType.OK, {"n": 1}))
    await dispatcher.dispatch(Event(EventType.OK, {"n": 2}))
    await _stop_within(dispatcher)

    assert seen == [1, 2]
    assert dispatcher._task is None


async def test_stop_before_the_loop_has_run():
    """An event dispatched straight after start(), before the loop's first
    turn, is handled too."""
    dispatcher = EventDispatcher()
    seen = []
    dispatcher.subscribe(EventType.OK, lambda event: seen.append(event.payload["n"]))
    await dispatcher.start()

    await dispatcher.dispatch(Event(EventType.OK, {"n": 1}))
    await _stop_within(dispatcher)

    assert seen == [1]
    assert dispatcher._task is None
