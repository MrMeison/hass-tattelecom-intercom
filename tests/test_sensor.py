"""Tests for the tattelecom_intercom component."""

# pylint: disable=no-member,too-many-statements,protected-access,too-many-lines

from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.sensor import ENTITY_ID_FORMAT as SENSOR_ENTITY_ID_FORMAT
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util.dt import utcnow
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.tattelecom_intercom.const import (
    ATTRIBUTION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SENSOR_CALL_STATE,
    SENSOR_SIP_STATE,
    SENSOR_SIP_STATE_NAME,
    SIGNAL_CALL_STATE,
    UPDATER,
)
from custom_components.tattelecom_intercom.enum import CallState, VoipState
from custom_components.tattelecom_intercom.exceptions import (
    IntercomConnectionError,
    IntercomError,
)
from custom_components.tattelecom_intercom.helper import generate_entity_id
from custom_components.tattelecom_intercom.updater import IntercomUpdater
from custom_components.tattelecom_intercom.voip import Call
from tests.setup import async_mock_client, async_setup, MOCK_IP

_LOGGER = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations"""

    yield


@pytest.mark.asyncio
async def test_init(hass: HomeAssistant) -> None:
    """Test init.

    :param hass: HomeAssistant
    """

    with patch(
        "custom_components.tattelecom_intercom.updater.IntercomClient"
    ) as mock_client, patch(
        "custom_components.tattelecom_intercom.updater.asyncio.sleep", return_value=None
    ), patch(
        "custom_components.tattelecom_intercom.sip.socket.socket"
    ) as mock_socket:
        mock_socket.return_value.setblocking = Mock(return_value=None)
        mock_socket.return_value.recv = Mock(return_value=None)
        mock_socket.return_value.sendto = Mock(side_effect=IntercomError)

        await async_mock_client(mock_client)

        _, config_entry = await async_setup(hass)

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        async_fire_time_changed(
            hass, utcnow() + timedelta(seconds=DEFAULT_SCAN_INTERVAL + 1)
        )
        await hass.async_block_till_done()

        updater: IntercomUpdater = hass.data[DOMAIN][config_entry.entry_id][UPDATER]

        assert updater.last_update_success

        state: State = hass.states.get(_generate_id(SENSOR_SIP_STATE, updater.phone))
        assert state.state == VoipState.INACTIVE.value
        assert state.name == SENSOR_SIP_STATE_NAME
        assert state.attributes["attribution"] == ATTRIBUTION


@pytest.mark.asyncio
async def test_update_state(hass: HomeAssistant) -> None:
    """Test update state.

    :param hass: HomeAssistant
    """

    with patch(
        "custom_components.tattelecom_intercom.updater.IntercomClient"
    ) as mock_client, patch(
        "custom_components.tattelecom_intercom.updater.asyncio.sleep", return_value=None
    ), patch(
        "custom_components.tattelecom_intercom.sip.socket.socket"
    ) as mock_socket:
        mock_socket.return_value.setblocking = Mock(return_value=None)
        mock_socket.return_value.recv = Mock(return_value=None)
        mock_socket.return_value.sendto = Mock(side_effect=IntercomError)

        await async_mock_client(mock_client)

        _, config_entry = await async_setup(hass)

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        updater: IntercomUpdater = hass.data[DOMAIN][config_entry.entry_id][UPDATER]
        registry = er.async_get(hass)

        assert updater.last_update_success

        unique_id: str = _generate_id(SENSOR_SIP_STATE, updater.phone)

        entry: er.RegistryEntry | None = registry.async_get(unique_id)
        state: State = hass.states.get(unique_id)
        assert state.state == VoipState.INACTIVE
        assert state.name == SENSOR_SIP_STATE_NAME
        assert state.attributes["attribution"] == ATTRIBUTION
        assert entry is not None
        assert entry.entity_category == EntityCategory.DIAGNOSTIC

        updater.voip._change_status(VoipState.FAILED)  # type: ignore

        async_fire_time_changed(
            hass, utcnow() + timedelta(seconds=DEFAULT_SCAN_INTERVAL + 1)
        )
        await hass.async_block_till_done()

        state = hass.states.get(unique_id)
        assert state.state == VoipState.FAILED


@pytest.mark.asyncio
async def test_sensor_available_during_api_failure(hass: HomeAssistant) -> None:
    """Test SIP/Call sensors stay available when API intercoms() fails.

    SIP and Call State sensors work via UDP dispatcher signals, independent
    of HTTP API. They should remain available even when coordinator fails
    to refresh intercoms.

    :param hass: HomeAssistant
    """

    with patch(
        "custom_components.tattelecom_intercom.updater.IntercomClient"
    ) as mock_client, patch(
        "custom_components.tattelecom_intercom.updater.asyncio.sleep", return_value=None
    ), patch(
        "custom_components.tattelecom_intercom.sip.socket.socket"
    ) as mock_socket:
        mock_socket.return_value.setblocking = Mock(return_value=None)
        mock_socket.return_value.recv = Mock(return_value=None)
        mock_socket.return_value.sendto = Mock(side_effect=IntercomError)

        await async_mock_client(mock_client)

        _, config_entry = await async_setup(hass)

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        updater: IntercomUpdater = hass.data[DOMAIN][config_entry.entry_id][UPDATER]
        assert updater.last_update_success

        sip_id: str = _generate_id(SENSOR_SIP_STATE, updater.phone)
        call_id: str = _generate_id(SENSOR_CALL_STATE, updater.phone)

        state: State = hass.states.get(sip_id)
        assert state.state == VoipState.INACTIVE.value

        state = hass.states.get(call_id)
        assert state.state == CallState.ENDED.value

        # Make intercoms() fail — coordinator uses cached data (graceful fallback)
        mock_client.return_value.intercoms = AsyncMock(
            side_effect=IntercomConnectionError("API unavailable")
        )

        async_fire_time_changed(
            hass, utcnow() + timedelta(seconds=DEFAULT_SCAN_INTERVAL + 1)
        )
        await hass.async_block_till_done()

        # Coordinator should still succeed due to graceful fallback
        assert updater.last_update_success

        # Sensors should remain available and show correct state
        state = hass.states.get(sip_id)
        assert state.state != "unavailable"
        assert state.state == VoipState.INACTIVE.value

        state = hass.states.get(call_id)
        assert state.state != "unavailable"
        assert state.state == CallState.ENDED.value


@pytest.mark.asyncio
async def test_call_state_updates_on_signal(hass: HomeAssistant) -> None:
    """Test Call State sensor updates when SIGNAL_CALL_STATE is dispatched.

    Simulates an incoming SIP call by setting updater.last_call and
    dispatching SIGNAL_CALL_STATE signal.

    :param hass: HomeAssistant
    """

    with patch(
        "custom_components.tattelecom_intercom.updater.IntercomClient"
    ) as mock_client, patch(
        "custom_components.tattelecom_intercom.updater.asyncio.sleep", return_value=None
    ), patch(
        "custom_components.tattelecom_intercom.sip.socket.socket"
    ) as mock_socket:
        mock_socket.return_value.setblocking = Mock(return_value=None)
        mock_socket.return_value.recv = Mock(return_value=None)
        mock_socket.return_value.sendto = Mock(side_effect=IntercomError)

        await async_mock_client(mock_client)

        _, config_entry = await async_setup(hass)

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        updater: IntercomUpdater = hass.data[DOMAIN][config_entry.entry_id][UPDATER]
        call_entity_id: str = _generate_id(SENSOR_CALL_STATE, updater.phone)

        # Initial state should be "ended"
        state: State = hass.states.get(call_entity_id)
        assert state.state == CallState.ENDED.value

        # Simulate incoming call: create a mock Call with RINGING state
        mock_call = Mock(spec=Call)
        mock_call.state = CallState.RINGING

        updater.last_call = mock_call
        async_dispatcher_send(hass, SIGNAL_CALL_STATE)
        await hass.async_block_till_done()

        state = hass.states.get(call_entity_id)
        assert state.state == CallState.RINGING.value

        # Simulate call answered
        mock_call.state = CallState.ANSWERED
        async_dispatcher_send(hass, SIGNAL_CALL_STATE)
        await hass.async_block_till_done()

        state = hass.states.get(call_entity_id)
        assert state.state == CallState.ANSWERED.value

        # Simulate call ended
        mock_call.state = CallState.ENDED
        async_dispatcher_send(hass, SIGNAL_CALL_STATE)
        await hass.async_block_till_done()

        state = hass.states.get(call_entity_id)
        assert state.state == CallState.ENDED.value


def _generate_id(code: str, phone: int) -> str:
    """Generate unique id

    :param code: str
    :param phone: int
    :return str
    """

    return generate_entity_id(
        SENSOR_ENTITY_ID_FORMAT,
        phone,
        code,
    )
