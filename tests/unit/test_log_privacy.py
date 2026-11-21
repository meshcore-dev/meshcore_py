"""Private values stay out of the log lines that name them (#119: A5, B6)."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from meshcore.commands import CommandHandler
from meshcore.events import Event, Subscription
from meshcore.reader import MessageReader

pytestmark = pytest.mark.asyncio

PUBKEY_HEX = "0123456789abcdef" * 4


class MockDispatcher:
    def __init__(self):
        self.dispatched_events = []

    async def dispatch(self, event):
        self.dispatched_events.append(event)


@pytest.fixture
def command_handler():
    """A CommandHandler whose every expected event is answered at once."""
    dispatcher = MagicMock()

    def subscribe(event_type, handler, attribute_filters=None):
        asyncio.get_event_loop().call_soon(handler, Event(event_type, {}))
        return MagicMock(spec=Subscription)

    dispatcher.subscribe = MagicMock(side_effect=subscribe)
    handler = CommandHandler()
    handler._sender_func = AsyncMock()
    handler.dispatcher = dispatcher
    return handler


def _logged(caplog):
    return "\n".join(r.getMessage() for r in caplog.records)


async def test_parse_error_line_leaves_out_the_frame(caplog):
    # A CONTACT frame cut after its key: reading the type byte raises.
    text = b"meet me at the north gate at ten"
    frame = bytearray(b"\x03" + text)

    with caplog.at_level(logging.ERROR, logger="meshcore"):
        await MessageReader(MockDispatcher()).handle_rx(frame)

    logged = _logged(caplog)
    assert "handle_rx parse error" in logged
    assert "packet type 0x03" in logged
    assert frame.hex() not in logged
    assert text.hex() not in logged
    assert text.decode() not in logged


async def test_set_devicepin_does_not_log_the_pin(command_handler, caplog):
    with caplog.at_level(logging.DEBUG, logger="meshcore"):
        await command_handler.set_devicepin(987654)

    assert "987654" not in _logged(caplog)


async def test_run_cli_command_does_not_log_the_command(command_handler, caplog):
    with caplog.at_level(logging.DEBUG, logger="meshcore"):
        await command_handler.run_cli_command("password hunter2")

    assert "hunter2" not in _logged(caplog)


async def test_send_cmd_does_not_log_the_command(command_handler, caplog):
    with caplog.at_level(logging.DEBUG, logger="meshcore"):
        await command_handler.send_cmd(PUBKEY_HEX, "password hunter2", dst_type=2)

    assert "hunter2" not in _logged(caplog)
