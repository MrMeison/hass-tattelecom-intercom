"""Tests for the tattelecom_intercom component."""

# pylint: disable=no-member,too-many-statements,protected-access,too-many-lines

from __future__ import annotations

import logging
from unittest.mock import Mock, patch, AsyncMock
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tattelecom_intercom.const import DOMAIN, UPDATER
from custom_components.tattelecom_intercom.exceptions import IntercomError
from custom_components.tattelecom_intercom.updater import async_get_updater, IntercomUpdater
from tests.setup import async_mock_client, async_setup

_LOGGER = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations"""

    yield


@pytest.mark.asyncio
async def test_updater_schedule(hass: HomeAssistant) -> None:
    """Test updater schedule.

    :param hass: HomeAssistant
    """

    updater, _ = await async_setup(hass)

    assert updater._unsub_refresh is None

    updater.schedule_refresh(updater._update_interval)
    updater.schedule_refresh(updater._update_interval)

    assert updater._unsub_refresh is not None


@pytest.mark.asyncio
async def test_updater_get_updater(hass: HomeAssistant) -> None:
    """Test updater get updater.

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

        assert hass.data[DOMAIN][config_entry.entry_id][UPDATER] == async_get_updater(
            hass, config_entry.entry_id
        )

        with pytest.raises(ValueError):
            async_get_updater(hass, "incorrect")


async def test_coordinator_update(hass: HomeAssistant):
    """Test coordinator update."""
    mock_client = AsyncMock()
    mock_client.get_intercoms.return_value = {"test": "data"}
    
    with patch(
        "custom_components.tattelecom_intercom.updater.IntercomClient",
        return_value=mock_client,
    ):
        coordinator = IntercomUpdater(
            hass,
            phone="1234567890",
            token="test_token",
            scan_interval=30,
        )
        
        await coordinator.async_config_entry_first_refresh()
        
        assert coordinator.data == {"test": "data"}
        assert coordinator.update_interval == timedelta(seconds=30)
        mock_client.get_intercoms.assert_called_once()


async def test_coordinator_update_failure(hass: HomeAssistant):
    """Test coordinator update failure."""
    mock_client = AsyncMock()
    mock_client.get_intercoms.side_effect = Exception("Test error")
    
    with patch(
        "custom_components.tattelecom_intercom.updater.IntercomClient",
        return_value=mock_client,
    ):
        coordinator = IntercomUpdater(
            hass,
            phone="1234567890",
            token="test_token",
        )
        
        with pytest.raises(UpdateFailed):
            await coordinator.async_config_entry_first_refresh()
