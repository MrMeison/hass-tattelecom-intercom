"""Tests for SIP re-registration scheduling (server-side expires)."""

# pylint: disable=protected-access

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import load_fixture

from custom_components.tattelecom_intercom.sip import IntercomSip, _SipState
from tests.setup import (
    MOCK_ADDRESS,
    MOCK_IP,
    MOCK_PASSWORD,
    MOCK_PORT,
    MOCK_USERNAME,
)


def _build_sip(hass: HomeAssistant) -> IntercomSip:
    """Build IntercomSip with mock callbacks

    :param hass: HomeAssistant
    :return IntercomSip
    """

    return IntercomSip(
        hass,
        MOCK_ADDRESS,
        MOCK_PORT,
        MOCK_USERNAME,
        MOCK_PASSWORD,
        MOCK_IP,
        Mock(),
        Mock(),
        Mock(),
    )


@pytest.mark.asyncio
async def test_reregister_uses_server_expires(hass: HomeAssistant) -> None:
    """Timer is set to server expires (300) minus 10, not the client 3600."""

    sip = _build_sip(hass)
    sip._state = _SipState.STARTING

    responses = [
        str.encode(load_fixture("register_first_data.txt")),
        str.encode(
            load_fixture("register_data.txt").replace("expires=3600", "expires=300")
        ),
    ]

    unsub = Mock()

    with patch.object(sip, "_send", AsyncMock()), patch.object(
        sip, "_recv_with_timeout", AsyncMock(side_effect=responses)
    ), patch(
        "custom_components.tattelecom_intercom.sip.async_call_later",
        return_value=unsub,
    ) as mock_later:
        await sip._register()

    assert mock_later.call_count == 1
    assert mock_later.call_args[0][1] == 290
    assert sip._cancel_register_timer is unsub


@pytest.mark.asyncio
async def test_reregister_timer_floor(hass: HomeAssistant) -> None:
    """Absurdly small server expires is clamped to the 30s floor."""

    sip = _build_sip(hass)
    sip._state = _SipState.STARTING

    responses = [
        str.encode(load_fixture("register_first_data.txt")),
        str.encode(
            load_fixture("register_data.txt").replace("expires=3600", "expires=15")
        ),
    ]

    with patch.object(sip, "_send", AsyncMock()), patch.object(
        sip, "_recv_with_timeout", AsyncMock(side_effect=responses)
    ), patch(
        "custom_components.tattelecom_intercom.sip.async_call_later",
        return_value=Mock(),
    ) as mock_later:
        await sip._register()

    assert mock_later.call_args[0][1] == 30


@pytest.mark.asyncio
async def test_set_register_timer_cancels_previous(hass: HomeAssistant) -> None:
    """A new timer unsubscribes the previous one (no parallel timers)."""

    sip = _build_sip(hass)

    unsub_one = Mock()
    unsub_two = Mock()

    with patch(
        "custom_components.tattelecom_intercom.sip.async_call_later",
        side_effect=[unsub_one, unsub_two],
    ):
        sip._set_register_timer(10, Mock())
        unsub_one.assert_not_called()

        sip._set_register_timer(10, Mock())
        unsub_one.assert_called_once()
        assert sip._cancel_register_timer is unsub_two


@pytest.mark.asyncio
async def test_stop_cancels_register_timer(hass: HomeAssistant) -> None:
    """stop() calls the unsubscribe callback instead of .cancel()."""

    sip = _build_sip(hass)
    sip._state = _SipState.STOPPED

    unsub = Mock()

    with patch(
        "custom_components.tattelecom_intercom.sip.async_call_later",
        return_value=unsub,
    ):
        sip._set_register_timer(10, Mock())

    await sip.stop()

    unsub.assert_called_once()
    assert sip._cancel_register_timer is None
