"""Tests for the tattelecom_intercom binary sensor component."""

# pylint: disable=no-member,too-many-statements,protected-access,too-many-lines

from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT as BINARY_SENSOR_ENTITY_ID_FORMAT,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.util.dt import utcnow
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.tattelecom_intercom.const import (
    ATTR_UPDATE_STATE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    UPDATER,
)
from custom_components.tattelecom_intercom.exceptions import (
    IntercomConnectionError,
    IntercomError,
)
from custom_components.tattelecom_intercom.helper import generate_entity_id
from custom_components.tattelecom_intercom.updater import IntercomUpdater
from tests.setup import async_mock_client, async_setup

_LOGGER = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations"""

    yield


def _generate_id(code: str, phone: int) -> str:
    """Generate unique id"""

    return generate_entity_id(
        BINARY_SENSOR_ENTITY_ID_FORMAT,
        phone,
        code,
    )


@pytest.mark.asyncio
async def test_binary_sensor_update_state_ok(hass: HomeAssistant) -> None:
    """Test binary sensor shows 'off' (no problem) after successful init.

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

        unique_id: str = _generate_id(ATTR_UPDATE_STATE, updater.phone)
        state: State = hass.states.get(unique_id)

        # update_state=True means success → binary sensor should be "off" (no problem)
        assert state.state == "off"


@pytest.mark.asyncio
async def test_binary_sensor_survives_api_failure(hass: HomeAssistant) -> None:
    """Test binary sensor stays 'off' when subsequent API call fails.

    After successful init, if intercoms() fails on refresh, the coordinator
    should still succeed using cached data (graceful fallback).

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

        unique_id: str = _generate_id(ATTR_UPDATE_STATE, updater.phone)

        # Now make intercoms() fail on next update
        mock_client.return_value.intercoms = AsyncMock(
            side_effect=IntercomConnectionError("API unavailable")
        )

        async_fire_time_changed(
            hass, utcnow() + timedelta(seconds=DEFAULT_SCAN_INTERVAL + 1)
        )
        await hass.async_block_till_done()

        # Coordinator should still succeed (graceful fallback)
        assert updater.last_update_success

        state: State = hass.states.get(unique_id)
        # Binary sensor should still show "off" (no problem)
        assert state.state == "off"
