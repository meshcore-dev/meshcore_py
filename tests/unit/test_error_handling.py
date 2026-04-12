"""Verification tests for error response handling fixes.

The tests confirm that error responses are surfaced cleanly instead
of causing KeyError, TypeError, NameError, or silent fallthrough.
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from meshcore.commands import CommandHandler
from meshcore.events import EventType, Event, Subscription

pytestmark = pytest.mark.asyncio

VALID_PUBKEY_HEX = "0123456789abcdef" * 4  # 64 hex chars = 32 bytes


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def mock_connection():
    connection = MagicMock()
    connection.send = AsyncMock()
    return connection


@pytest.fixture
def mock_dispatcher():
    dispatcher = MagicMock()
    dispatcher.wait_for_event = AsyncMock()
    dispatcher.dispatch = AsyncMock()

    def fake_subscribe(event_type, handler, attribute_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        dispatcher._last_subscribe_handler = handler
        dispatcher._last_subscribe_event_type = event_type
        return sub

    dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)
    return dispatcher


@pytest.fixture
def command_handler(mock_connection, mock_dispatcher):
    handler = CommandHandler()

    async def sender(data):
        await mock_connection.send(data)

    handler._sender_func = sender
    handler.dispatcher = mock_dispatcher
    return handler


def setup_error_response(mock_dispatcher):
    """Configure dispatcher to return an ERROR event for any subscribe."""
    def fake_subscribe(evt_type, handler, attr_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        # Always fire ERROR regardless of which event type was subscribed
        if evt_type == EventType.ERROR:
            asyncio.get_event_loop().call_soon(
                handler, Event(EventType.ERROR, {"reason": "test_error"})
            )
        return sub

    mock_dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)


def setup_event_response(mock_dispatcher, event_type, payload):
    """Configure dispatcher to return a specific event."""
    def fake_subscribe(evt_type, handler, attr_filters=None):
        sub = MagicMock(spec=Subscription)
        sub.unsubscribe = MagicMock()
        if evt_type == event_type:
            asyncio.get_event_loop().call_soon(
                handler, Event(event_type, payload)
            )
        return sub

    mock_dispatcher.subscribe = MagicMock(side_effect=fake_subscribe)


# ── Event.is_error() helper ──────────────────────────────────

async def test_event_is_error_true():
    """is_error() returns True for ERROR events."""
    event = Event(EventType.ERROR, {"reason": "test"})
    assert event.is_error() is True


async def test_event_is_error_false():
    """is_error() returns False for non-ERROR events."""
    event = Event(EventType.OK, {})
    assert event.is_error() is False
    event2 = Event(EventType.SELF_INFO, {"name": "test"})
    assert event2.is_error() is False


# ── send_msg_with_retry continues on ERROR ──────────────

async def test_send_msg_with_retry_error_no_keyerror(
    command_handler, mock_dispatcher
):
    """send_msg_with_retry returns None (exhausted retries) on
    persistent ERROR instead of raising KeyError on missing 'expected_ack'."""
    setup_error_response(mock_dispatcher)

    # Provide a mock contact so the path logic doesn't interfere
    command_handler._get_contact_by_prefix = MagicMock(return_value=None)

    # max_attempts=2 so it retries once then gives up
    result = await command_handler.send_msg_with_retry(
        VALID_PUBKEY_HEX, "hello", max_attempts=2, timeout=0.1
    )

    # Should return None (no ACK received) rather than raising KeyError
    assert result is None


# ── send_appstart includes ERROR in expected events ──────────

async def test_send_appstart_returns_error(
    command_handler, mock_dispatcher
):
    """send_appstart returns ERROR event instead of hanging on timeout."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.send_appstart()

    assert result.type == EventType.ERROR
    assert result.is_error() is True
    assert result.payload["reason"] == "test_error"


# ── device setters return ERROR from send_appstart ───────────

async def test_set_telemetry_mode_base_error(
    command_handler, mock_dispatcher
):
    """set_telemetry_mode_base returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_telemetry_mode_base(1)

    assert result.is_error()
    assert result.payload["reason"] == "test_error"


async def test_set_telemetry_mode_loc_error(
    command_handler, mock_dispatcher
):
    """set_telemetry_mode_loc returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_telemetry_mode_loc(1)

    assert result.is_error()


async def test_set_telemetry_mode_env_error(
    command_handler, mock_dispatcher
):
    """set_telemetry_mode_env returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_telemetry_mode_env(1)

    assert result.is_error()


async def test_set_manual_add_contacts_error(
    command_handler, mock_dispatcher
):
    """set_manual_add_contacts returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_manual_add_contacts(True)

    assert result.is_error()


async def test_set_advert_loc_policy_error(
    command_handler, mock_dispatcher
):
    """set_advert_loc_policy returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_advert_loc_policy(1)

    assert result.is_error()


async def test_set_multi_acks_error(
    command_handler, mock_dispatcher
):
    """set_multi_acks returns ERROR instead of KeyError."""
    setup_error_response(mock_dispatcher)

    result = await command_handler.set_multi_acks(1)

    assert result.is_error()


# ── send_anon_req returns ERROR on contact not found ─────────

async def test_send_anon_req_contact_not_found(
    command_handler, mock_dispatcher
):
    """send_anon_req returns ERROR event when contact prefix not found,
    instead of raising TypeError on NoneType subscript."""
    command_handler._get_contact_by_prefix = MagicMock(return_value=None)

    result = await command_handler.send_anon_req(
        VALID_PUBKEY_HEX, MagicMock(value=1)
    )

    assert result.is_error()
    assert result.payload["reason"] == "contact_not_found"


# ── send_trace handles unknown path_hash_len without NameError ──

async def test_send_trace_unknown_path_hash_len(
    command_handler, mock_connection, mock_dispatcher
):
    """send_trace with a path whose segments don't match any known
    path_hash_len returns ERROR cleanly instead of NameError on 'e'."""
    # 5-char hex segments → path_hash_len = 2.5 → doesn't match 1,2,4,8
    result = await command_handler.send_trace(
        auth_code=0, tag=1, flags=None, path="abcde"
    )

    assert result.is_error()
    assert result.payload["reason"] == "invalid_path_format"
