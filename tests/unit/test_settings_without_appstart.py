"""The single-setting calls use the self info already held, not a new APP_START (#119: B3).

The firmware's APP_START stops a contact list it is sending, so a get_contacts in progress never ends.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from meshcore import MeshCore
from meshcore.commands import CommandHandler
from meshcore.events import Event, EventType, Subscription

pytestmark = pytest.mark.asyncio

APP_START = 0x01
SET_OTHER_PARAMS = 0x26

SELF_INFO = {
    "name": "Me",
    "manual_add_contacts": False,
    "telemetry_mode_base": 1,
    "telemetry_mode_loc": 2,
    "telemetry_mode_env": 0,
    "adv_loc_policy": 1,
    "multi_acks": 0,
}


@pytest.fixture
def handler():
    """A CommandHandler on a radio that answers APP_START with SELF_INFO and
    anything else with OK, keeping every frame sent."""
    dispatcher = MagicMock()

    def subscribe(event_type, callback, attribute_filters=None):
        payload = dict(SELF_INFO) if event_type == EventType.SELF_INFO else {}
        if event_type in (EventType.SELF_INFO, EventType.OK):
            asyncio.get_event_loop().call_soon(callback, Event(event_type, payload))
        return MagicMock(spec=Subscription)

    dispatcher.subscribe = MagicMock(side_effect=subscribe)
    handler = CommandHandler()
    handler.sent = []

    async def sender(data):
        handler.sent.append(bytes(data))

    handler._sender_func = sender
    handler.dispatcher = dispatcher
    return handler


def other_params(manual_add, base, loc, env, loc_policy, multi_acks):
    return bytes([SET_OTHER_PARAMS, manual_add, base | loc << 2 | env << 4, loc_policy, multi_acks])


async def test_held_self_info_is_used_and_no_app_start_is_sent(handler):
    held = dict(SELF_INFO)
    handler.set_self_info_getter(lambda: held)

    result = await handler.set_manual_add_contacts(True)

    assert result.type == EventType.OK
    assert handler.sent == [other_params(1, 1, 2, 0, 1, 0)]
    assert held["manual_add_contacts"] is True


async def test_a_second_setting_keeps_the_first(handler):
    held = dict(SELF_INFO)
    handler.set_self_info_getter(lambda: held)

    await handler.set_telemetry_mode_env(3)
    await handler.set_multi_acks(1)

    assert handler.sent == [other_params(0, 1, 2, 3, 1, 0), other_params(0, 1, 2, 3, 1, 1)]
    assert [frame[0] for frame in handler.sent].count(APP_START) == 0


async def test_app_start_is_sent_when_no_self_info_is_held(handler):
    result = await handler.set_advert_loc_policy(0)

    assert result.type == EventType.OK
    assert [frame[0] for frame in handler.sent] == [APP_START, SET_OTHER_PARAMS]
    assert handler.sent[1] == other_params(0, 1, 2, 0, 0, 0)


async def test_app_start_is_sent_when_the_held_self_info_is_empty(handler):
    # MeshCore holds {} until its first SELF_INFO
    handler.set_self_info_getter(lambda: {})

    await handler.set_advert_loc_policy(0)

    assert [frame[0] for frame in handler.sent] == [APP_START, SET_OTHER_PARAMS]


async def test_meshcore_gives_its_commands_the_self_info_it_holds():
    cx = MagicMock()
    cx.send = AsyncMock()
    mc = MeshCore(cx)
    mc._self_info = dict(SELF_INFO)

    assert mc.commands._get_self_info() is mc._self_info
