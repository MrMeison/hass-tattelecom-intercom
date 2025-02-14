"""Tattelecom Intercom updater."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
import logging
from random import randint
from functools import cached_property
from dataclasses import dataclass
from typing import Any, Callable, Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import event
from homeassistant.util.dt import utcnow
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from httpx import AsyncHTTPTransport, codes

from .const import (
    ATTR_MUTE,
    ATTR_SIP_LOGIN,
    ATTR_STREAM_URL,
    ATTR_STREAM_URL_MPEG,
    ATTR_SIP_ADDRESS,
    ATTR_SIP_PORT,
    ATTR_SIP_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    SIP_DEFAULT_RETRY,
    DOMAIN,
    MAINTAINER,
    NAME,
    SIGNAL_NEW_INTERCOM,
    UPDATER,
)
from .exceptions import IntercomConnectionError
from .client import IntercomClient
from .voip import IntercomVoip, Call

CALLBACK_TYPE = Callable[[Any], None]

_LOGGER = logging.getLogger(__name__)


# pylint: disable=too-many-branches,too-many-lines,too-many-arguments
class IntercomUpdater(DataUpdateCoordinator[dict[str, Any]]):
    """Tattelecom Intercom data updater."""

    client: IntercomClient

    voip: IntercomVoip | None = None
    last_call: Call | None = None

    code: codes = codes.BAD_GATEWAY

    phone: int
    token: str

    new_intercom_callbacks: list[CALLBACK_TYPE] = []

    _scan_interval: int
    _is_first_update: bool

    def __init__(
        self,
        hass: HomeAssistant,
        phone: int,
        token: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize updater."""
        
        super().__init__(
            hass,
            _LOGGER,
            name=f"{NAME} updater",
            update_interval=timedelta(seconds=scan_interval),
        )

        self.phone = phone
        self.token = token
        self._scan_interval = scan_interval
        self._is_first_update = True
        
        _transport = AsyncHTTPTransport(http1=False, http2=True, retries=3)
        self.client = IntercomClient(
            create_async_httpx_client(
                hass, True, http1=False, http2=True, transport=_transport
            ),
            phone,
            token,
            timeout,
        )

        self.voip: IntercomVoip | None = None
        self.last_call: Call | None = None
        self.code = codes.BAD_GATEWAY
        self.new_intercom_callbacks: list[CALLBACK_TYPE] = []
        self.intercoms: dict[int, IntercomEntityDescription] = {}
        self.code_map: dict[str, int] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data."""
        try:
            data: dict = {}
            await self._async_prepare_intercoms(data)
            return data
        except Exception as exc:
            raise UpdateFailed(f"Error communicating with API: {exc}") from exc

    async def async_stop(self) -> None:
        """Stop updater"""

        for _callback in self.new_intercom_callbacks:
            _callback()  # pylint: disable=not-callable

        if self.voip:
            await self.voip.stop()

    @cached_property
    def _update_interval(self) -> timedelta:
        """Update interval

        :return timedelta: update_interval
        """

        return timedelta(seconds=self._scan_interval)

    def update_data(self, field: str, value: Any) -> None:
        """Update data

        :param field: str
        :param value: Any
        """

        self.data[field] = value

    @property
    def device_info(self) -> DeviceInfo:
        """Device info.

        :return DeviceInfo: Service DeviceInfo.
        """

        return DeviceInfo(
            identifiers={(DOMAIN, str(self.phone))},
            name=NAME,
            manufacturer=MAINTAINER,
        )

    def schedule_refresh(self, offset: timedelta) -> None:
        """Schedule refresh.

        :param offset: timedelta
        """

        if self._unsub_refresh:  # type: ignore
            self._unsub_refresh()  # type: ignore
            self._unsub_refresh = None

        self._unsub_refresh = event.async_track_point_in_utc_time(
            self.hass,
            self._job,
            utcnow().replace(microsecond=0) + offset,
        )

    async def _async_prepare(self, data: dict, retry: int = 1) -> None:
        """Prepare data.

        :param data: dict
        :param retry: int
        """

        _error: IntercomConnectionError | None = None

        try:
            await self._async_prepare_sip_settings(data)
            self._is_first_update = False
        except IntercomConnectionError as _err:  # pragma: no cover
            _error = _err

        await asyncio.sleep(randint(5, 10))

        try:
            await self._async_prepare_intercoms(data)
        except IntercomConnectionError as _err:  # pragma: no cover
            _error = _err

        with contextlib.suppress(IntercomConnectionError):
            await self.client.streams()

        if _error:  # pragma: no cover
            if self._is_first_update and retry <= SIP_DEFAULT_RETRY:
                await asyncio.sleep(retry)

                _LOGGER.debug("Error start. retry (%r): %r", retry, _error)

                return await self._async_prepare(data, retry + 1)

            raise _error

    async def _async_prepare_intercoms(self, data: dict) -> None:
        """Prepare intercoms.

        :param data: dict
        """

        response: dict = await self.client.intercoms()

        if "addresses" in response:
            for address, intercoms in response["addresses"].items():
                for intercom in intercoms:
                    if (
                        ATTR_STREAM_URL in intercom and ATTR_STREAM_URL_MPEG in intercom
                    ):  # pragma: no cover
                        intercom[ATTR_STREAM_URL] = intercom[ATTR_STREAM_URL_MPEG]

                    for attr in [ATTR_STREAM_URL, ATTR_MUTE, ATTR_SIP_LOGIN]:
                        data[f"{intercom['id']}_{attr}"] = intercom[attr]

                    if intercom["id"] in self.intercoms:
                        continue

                    self.code_map[intercom["sip_login"]] = intercom["id"]

                    self.intercoms[intercom["id"]] = IntercomEntityDescription(
                        id=intercom["id"],
                        device_info=DeviceInfo(
                            identifiers={(DOMAIN, str(intercom["id"]))},
                            name=" ".join(
                                [
                                    address,
                                    intercom.get(
                                        "gate_name", intercom.get("intercom_name", "")
                                    ),
                                ]
                            ).strip(),
                            manufacturer=MAINTAINER,
                        ),
                    )

                    if self.new_intercom_callbacks:
                        async_dispatcher_send(
                            self.hass,
                            SIGNAL_NEW_INTERCOM,
                            self.intercoms[intercom["id"]],
                        )

    async def _async_prepare_sip_settings(self, data: dict) -> None:
        """Prepare sip_settings.

        :param data: dict
        """

        response: dict = await self.client.sip_settings()

        init: bool = False
        if "success" in response and response["success"]:
            del response["success"]

            init = (
                len(
                    [
                        code
                        for code, value in response.items()
                        if code not in data or data[code] != value
                    ]
                )
                > 0
            )

            data |= response

        if init:
            self.voip = IntercomVoip(
                self.hass,
                data[ATTR_SIP_ADDRESS],
                data[ATTR_SIP_PORT],
                data[ATTR_SIP_LOGIN],
                data[ATTR_SIP_PASSWORD],
                self._call_callback,
            )

            self.hass.loop.call_soon(
                lambda: self.hass.async_create_task(
                    self.voip.safe_start(SIP_DEFAULT_RETRY)
                )
            )

    async def _call_callback(self, call: Call) -> None:  # pragma: no cover
        """Call callback

        :param call: Call
        """

        self.last_call = call

        async_dispatcher_send(self.hass, SIGNAL_CALL_STATE)


@dataclass
class IntercomEntityDescription:
    """Intercom entity description."""

    # pylint: disable=invalid-name
    id: int
    device_info: DeviceInfo


@callback
def async_get_updater(hass: HomeAssistant, identifier: str) -> IntercomUpdater:
    """Return IntercomUpdater for username or entry id.

    :param hass: HomeAssistant
    :param identifier: str
    :return IntercomUpdater
    """

    if (
        DOMAIN not in hass.data
        or identifier not in hass.data[DOMAIN]
        or UPDATER not in hass.data[DOMAIN][identifier]
    ):
        raise ValueError(f"Integration with identifier: {identifier} not found.")

    return hass.data[DOMAIN][identifier][UPDATER]
