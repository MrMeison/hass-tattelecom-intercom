"""Tests for push driven call state and bus events."""

# pylint: disable=protected-access

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Final
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.tattelecom_intercom.const import (
    EVENT_CALL_ENDED,
    EVENT_INCOMING_CALL,
    PUSH_CALL_TIMEOUT,
)
from custom_components.tattelecom_intercom.enum import CallState
from custom_components.tattelecom_intercom.updater import IntercomUpdater

from tests.setup import MOCK_PHONE, MOCK_TOKEN

_LOGGER = logging.getLogger(__name__)

MOCK_GATE_LOGIN: Final = "G17126"
MOCK_GATE_ID: Final = 17126
MOCK_SIP_LOGIN: Final = "D000000"

START_CALL_PUSH: Final = {
    "category": "start_call",
    "title": f"intercom_sip_login={MOCK_GATE_LOGIN}",
    "body": "startcall",
    "uuid": "srid-6a4cc94f",
    "sip_address": "dmf-proxy01.tattelecom.ru",
    "sip_port": "9741",
    "sip_transport": "tls",
    "sip_call_id": "dom2-aster-01-1785514214.1189358",
}


def _updater(hass: HomeAssistant) -> IntercomUpdater:
    """Updater with a known intercom, no network involved

    :param hass: HomeAssistant
    :return IntercomUpdater
    """

    updater: IntercomUpdater = IntercomUpdater(hass, MOCK_PHONE, MOCK_TOKEN)
    updater.code_map[MOCK_GATE_LOGIN] = MOCK_GATE_ID

    return updater


@pytest.mark.asyncio
async def test_push_start_call_fires_event(hass: HomeAssistant) -> None:
    """A start_call push must set the ringing state and fire an event"""

    updater: IntercomUpdater = _updater(hass)

    events: list[dict[str, Any]] = []
    hass.bus.async_listen(EVENT_INCOMING_CALL, lambda event: events.append(event.data))

    updater._push_callback(START_CALL_PUSH)
    await hass.async_block_till_done()

    assert updater.call_state == CallState.RINGING
    assert updater.call_login == MOCK_GATE_LOGIN

    assert len(events) == 1
    assert events[0]["gate_id"] == MOCK_GATE_ID
    assert events[0]["sip_login"] == MOCK_GATE_LOGIN
    assert events[0]["call_id"] == START_CALL_PUSH["sip_call_id"]
    assert events[0]["source"] == "push"

    await updater.async_stop()


@pytest.mark.asyncio
async def test_push_other_category_ignored(hass: HomeAssistant) -> None:
    """Pushes that are not calls must not touch the call state"""

    updater: IntercomUpdater = _updater(hass)

    events: list[dict[str, Any]] = []
    hass.bus.async_listen(EVENT_INCOMING_CALL, lambda event: events.append(event.data))

    updater._push_callback({"category": "message", "title": "hello"})
    await hass.async_block_till_done()

    assert updater.call_state == CallState.ENDED
    assert not events

    await updater.async_stop()


@pytest.mark.asyncio
async def test_push_call_times_out(hass: HomeAssistant) -> None:
    """Nothing reports the end of the call without SIP — the timer must do it"""

    updater: IntercomUpdater = _updater(hass)

    ended: list[dict[str, Any]] = []
    hass.bus.async_listen(EVENT_CALL_ENDED, lambda event: ended.append(event.data))

    updater._push_callback(START_CALL_PUSH)
    await hass.async_block_till_done()

    assert updater.call_state == CallState.RINGING
    assert updater._cancel_call_reset is not None

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=PUSH_CALL_TIMEOUT + 1)
    )
    await hass.async_block_till_done()

    assert updater.call_state == CallState.ENDED
    assert len(ended) == 1
    assert PUSH_CALL_TIMEOUT > 0

    await updater.async_stop()


@pytest.mark.asyncio
async def test_sip_disabled_skips_voip(hass: HomeAssistant) -> None:
    """The built-in SIP client is opt-in: settings are stored, nothing dials"""

    updater: IntercomUpdater = _updater(hass)

    assert updater.enable_sip is False

    updater.client = AsyncMock()  # type: ignore[assignment]
    updater.client.sip_settings = AsyncMock(
        return_value={
            "success": True,
            "sip_address": "dmf-proxy01.tattelecom.ru",
            "sip_port": 9740,
            "sip_login": MOCK_SIP_LOGIN,
            "sip_password": "secret",
            "reg_expire_time": 60,
        }
    )

    data: dict = {}
    await updater._async_prepare_sip_settings(data)
    await hass.async_block_till_done()

    assert updater.voip is None
    assert data["sip_login"] == MOCK_SIP_LOGIN

    await updater.async_stop()


@pytest.mark.asyncio
async def test_repeated_ring_fires_once(hass: HomeAssistant) -> None:
    """A second announcement of the same visit must not duplicate the event"""

    updater: IntercomUpdater = _updater(hass)

    events: list[dict[str, Any]] = []
    hass.bus.async_listen(EVENT_INCOMING_CALL, lambda event: events.append(event.data))

    updater._push_callback(START_CALL_PUSH)
    updater._push_callback(START_CALL_PUSH)
    await hass.async_block_till_done()

    assert updater.call_state == CallState.RINGING
    assert len(events) == 1

    await updater.async_stop()
