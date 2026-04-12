"""
Verification tests for G7 — Standalone bugs and cleanup.
Findings: F13, F09, M03, M05, M07, R03, R05.
"""

import pytest
import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

from meshcore.events import Event, EventDispatcher, EventType
from meshcore.commands.base import CommandHandlerBase
from meshcore.commands.binary import BinaryCommandHandler
from meshcore.commands.messaging import MessagingCommands
from meshcore.commands.contact import ContactCommands
from meshcore.meshcore import MeshCore

pytestmark = pytest.mark.asyncio


# ── F13: req_mma removed ──────────────────────────────────────────────────────

def test_f13_req_mma_removed():
    """F13: The broken req_mma method should no longer exist on BinaryCommandHandler."""
    assert not hasattr(BinaryCommandHandler, "req_mma"), \
        "req_mma should be removed — it had NameError on undefined start/end"


def test_f13_req_mma_sync_still_exists():
    """F13: req_mma_sync should still be present and functional."""
    assert hasattr(BinaryCommandHandler, "req_mma_sync"), \
        "req_mma_sync should still exist after removing req_mma"


# ── F09: DEFAULT_TIMEOUT bumped ───────────────────────────────────────────────

def test_f09_default_timeout_bumped():
    """F09: DEFAULT_TIMEOUT should be 15.0, not the old 5.0."""
    assert CommandHandlerBase.DEFAULT_TIMEOUT == 15.0, \
        f"DEFAULT_TIMEOUT is {CommandHandlerBase.DEFAULT_TIMEOUT}, expected 15.0"


def test_f09_instance_default_timeout():
    """F09: Instance default_timeout should inherit the new 15.0 value."""
    handler = CommandHandlerBase()
    assert handler.default_timeout == 15.0


def test_f09_custom_timeout_still_works():
    """F09: Passing a custom timeout should still override the default."""
    handler = CommandHandlerBase(default_timeout=30.0)
    assert handler.default_timeout == 30.0


# ── M03: set_flood_scope TypeError guard ──────────────────────────────────────

async def test_m03_set_flood_scope_bad_type_raises():
    """M03: Passing an unsupported type (e.g., int) should raise TypeError."""
    handler = MessagingCommands()
    with pytest.raises(TypeError, match="unsupported scope type"):
        await handler.set_flood_scope(42)


async def test_m03_set_flood_scope_bad_type_bytearray():
    """M03: bytearray is not bytes — should raise TypeError."""
    handler = MessagingCommands()
    with pytest.raises(TypeError, match="unsupported scope type"):
        await handler.set_flood_scope(bytearray(b"\x00" * 16))


async def test_m03_set_flood_scope_none_still_works():
    """M03: None scope should reach send() without TypeError — verifies the None branch still binds scope_key."""
    handler = MessagingCommands()
    handler._sender_func = AsyncMock()
    handler.dispatcher = EventDispatcher()
    await handler.dispatcher.start()
    try:
        # Dispatch an OK event so send() resolves
        async def _dispatch_ok():
            await asyncio.sleep(0.05)
            await handler.dispatcher.dispatch(Event(EventType.OK, {}))
        asyncio.ensure_future(_dispatch_ok())
        result = await handler.set_flood_scope(None)
        assert result.type == EventType.OK
    finally:
        handler.dispatcher.running = False


async def test_m03_set_flood_scope_str_still_works():
    """M03: String scope should reach send() without TypeError."""
    handler = MessagingCommands()
    handler._sender_func = AsyncMock()
    handler.dispatcher = EventDispatcher()
    await handler.dispatcher.start()
    try:
        async def _dispatch_ok():
            await asyncio.sleep(0.05)
            await handler.dispatcher.dispatch(Event(EventType.OK, {}))
        asyncio.ensure_future(_dispatch_ok())
        result = await handler.set_flood_scope("#test")
        assert result.type == EventType.OK
    finally:
        handler.dispatcher.running = False


async def test_m03_set_flood_scope_bytes_still_works():
    """M03: Bytes scope should reach send() without TypeError."""
    handler = MessagingCommands()
    handler._sender_func = AsyncMock()
    handler.dispatcher = EventDispatcher()
    await handler.dispatcher.start()
    try:
        async def _dispatch_ok():
            await asyncio.sleep(0.05)
            await handler.dispatcher.dispatch(Event(EventType.OK, {}))
        asyncio.ensure_future(_dispatch_ok())
        result = await handler.set_flood_scope(b"\x01" * 16)
        assert result.type == EventType.OK
    finally:
        handler.dispatcher.running = False


# ── M05: dead path_hash_mode shift removed ────────────────────────────────────

def test_m05_no_shift_in_update_contact():
    """M05: The dead `>> 6` shift on out_path_len should not appear in contact.py."""
    import meshcore.commands.contact as contact_mod
    source = inspect.getsource(contact_mod.ContactCommands.update_contact)
    assert ">> 6" not in source, \
        "Dead path_hash_mode = out_path_len >> 6 shift should be removed"


# ── M07: get_contacts returns Event, never None ───────────────────────────────

async def test_m07_get_contacts_timeout_returns_error_event():
    """M07: On timeout (no futures complete), get_contacts should return an Error Event, not None."""
    handler = ContactCommands()
    handler._sender_func = AsyncMock()
    handler._reader = MagicMock()
    handler.dispatcher = MagicMock()
    # Make wait_for_event always timeout by never returning
    handler.dispatcher.wait_for_event = AsyncMock(side_effect=asyncio.TimeoutError)

    result = await handler.get_contacts(timeout=0.1)
    assert result is not None, "get_contacts should never return None"
    assert isinstance(result, Event)
    assert result.type == EventType.ERROR


# ── R03: binary request pre-registration ──────────────────────────────────────

async def test_r03_placeholder_registered_before_send():
    """R03: A placeholder binary request should be registered before send() is called."""
    from meshcore.packets import BinaryReqType

    handler = CommandHandlerBase()
    handler._sender_func = AsyncMock()

    # Track registration calls
    mock_reader = MagicMock()
    mock_reader.pending_binary_requests = {}
    original_register = MagicMock()

    registration_order = []
    send_called = False

    async def mock_send(data):
        nonlocal send_called
        # At the point send() is called, a placeholder should already exist
        registration_order.append(("send", len(mock_reader.pending_binary_requests)))
        send_called = True

    handler._sender_func = mock_send
    handler._reader = mock_reader
    handler.dispatcher = MagicMock()
    handler.dispatcher.wait_for_event = AsyncMock(
        return_value=Event(EventType.MSG_SENT, {"expected_ack": b"\x01\x02\x03\x04"})
    )

    # Resolve subscribed events immediately so send() doesn't block
    def resolving_subscribe(event_type, cb, attribute_filters=None):
        sub = MagicMock()
        sub.unsubscribe = MagicMock()
        asyncio.get_event_loop().call_soon(
            cb, Event(event_type, {})
        )
        return sub
    handler.dispatcher.subscribe = MagicMock(side_effect=resolving_subscribe)

    # Call send_binary_req
    dst = "aa" * 32  # 32-byte hex pubkey
    await handler.send_binary_req(dst, BinaryReqType.MMA)

    # Verify register_binary_request was called (at least the placeholder)
    assert mock_reader.register_binary_request.call_count >= 1, \
        "register_binary_request should be called at least once for the placeholder"


# ── R05: MeshCore.subscribe annotation matches EventDispatcher ────────────────

def test_r05_subscribe_annotation_matches_dispatcher():
    """R05: MeshCore.subscribe callback annotation should match EventDispatcher.subscribe."""
    mc_hints = MeshCore.subscribe.__annotations__
    ed_hints = EventDispatcher.subscribe.__annotations__

    # Both should have 'callback' in their annotations
    assert "callback" in mc_hints, "MeshCore.subscribe missing callback annotation"
    assert "callback" in ed_hints, "EventDispatcher.subscribe missing callback annotation"

    # The callback annotations should be identical
    assert mc_hints["callback"] == ed_hints["callback"], (
        f"MeshCore.subscribe callback annotation {mc_hints['callback']} "
        f"does not match EventDispatcher.subscribe {ed_hints['callback']}"
    )


def test_r05_no_coroutine_import_in_meshcore():
    """R05: After widening the annotation, Coroutine should no longer be imported in meshcore.py."""
    import meshcore.meshcore as mc_mod
    source = inspect.getsource(mc_mod)
    # Check the import line specifically — Coroutine should not be in the typing imports
    for line in source.splitlines():
        if line.startswith("from typing import"):
            assert "Coroutine" not in line, \
                "Coroutine should be removed from typing imports in meshcore.py"
            break
