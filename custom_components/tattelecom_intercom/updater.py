"""Tattelecom Intercom updater."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
import logging
from random import randint
from functools import cached_property
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import event
from homeassistant.util.dt import utcnow
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
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
    ATTR_UPDATE_STATE,
    ATTR_SIP_ADDRESS,
    ATTR_SIP_PORT,
    ATTR_SIP_PASSWORD,
    ATTR_SIP_REG_EXPIRE_TIME,
    ATTR_PUSH_CALL_ID,
    ATTR_PUSH_CATEGORY,
    ATTR_PUSH_TITLE,
    ATTR_PUSH_TRANSPORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    EVENT_CALL_ANSWERED,
    EVENT_CALL_ENDED,
    EVENT_INCOMING_CALL,
    PUSH_CALL_TIMEOUT,
    PUSH_CATEGORY_START_CALL,
    SIP_DEFAULT_RETRY,
    DOMAIN,
    MAINTAINER,
    NAME,
    SIGNAL_NEW_INTERCOM,
    SIGNAL_CALL_STATE,
    UPDATER,
)
from .enum import CallState
from .exceptions import IntercomConnectionError, IntercomUnauthorizedError
from .client import IntercomClient
from .push import IntercomPush
from .voip import IntercomVoip, Call

CALLBACK_TYPE = Callable[[Any], None]

_LOGGER = logging.getLogger(__name__)


# pylint: disable=too-many-branches,too-many-lines,too-many-arguments
class IntercomUpdater(DataUpdateCoordinator[dict[str, Any]]):
    """Tattelecom Intercom data updater."""

    client: IntercomClient

    voip: IntercomVoip | None = None
    push: IntercomPush | None = None
    last_call: Call | None = None

    code: codes = codes.BAD_GATEWAY

    phone: int
    token: str
    enable_sip: bool

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
        enable_sip: bool = False,
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
        self.enable_sip = enable_sip
        self._scan_interval = scan_interval
        self._is_first_update = True
        self._timeout = timeout

        self.voip: IntercomVoip | None = None
        self.push: IntercomPush | None = None
        self.last_call: Call | None = None
        self.code = codes.BAD_GATEWAY
        self.new_intercom_callbacks: list[CALLBACK_TYPE] = []
        self.intercoms: dict[int, IntercomEntityDescription] = {}
        self.code_map: dict[str, int] = {}

        # Call state tracked independently of the SIP client: with SIP disabled
        # (calls answered by a PBX or not at all) the push is the only source.
        self.call_state: CallState = CallState.ENDED
        self.call_login: str | None = None
        self.call_info: dict[str, Any] = {}
        self._cancel_call_reset: CALLBACK_TYPE | None = None

    async def async_init(self) -> None:
        """Initialize HTTP client asynchronously to avoid blocking the event loop."""

        _transport = await self.hass.async_add_executor_job(
            lambda: AsyncHTTPTransport(http1=True, http2=True, retries=3)
        )
        self.client = IntercomClient(
            create_async_httpx_client(
                self.hass, True, http1=True, http2=True, transport=_transport
            ),
            self.phone,
            self.token,
            self._timeout,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data."""
        try:
            data: dict = {}
            if self._is_first_update:
                await self._async_prepare(data)
            else:
                data[ATTR_UPDATE_STATE] = True
                try:
                    await self._async_prepare_intercoms(data)
                except IntercomConnectionError:
                    _LOGGER.debug("Failed to refresh intercoms, using cached data")

                    if self.data:
                        for key, value in self.data.items():
                            if key not in data:
                                data[key] = value
            return data
        except IntercomUnauthorizedError as exc:
            # The operator rotates the session token (e.g. after a login in the
            # phone app). Hand over to the reauth flow instead of retrying with
            # credentials that will never work again.
            raise ConfigEntryAuthFailed(
                "Session token rejected by the operator, re-authorization required"
            ) from exc
        except Exception as exc:
            raise UpdateFailed(f"Error communicating with API: {exc}") from exc

    async def async_start_push(self) -> None:
        """Start push listener.

        Incoming calls are announced by a Firebase push, so this runs whether or
        not the built-in SIP client is enabled.
        """

        self.push = IntercomPush(self.hass, self.client, self._push_callback)

        if not await self.push.async_start():  # pragma: no cover
            self.push = None

    async def async_stop(self) -> None:
        """Stop updater"""

        for _callback in self.new_intercom_callbacks:
            _callback()  # pylint: disable=not-callable

        if self._cancel_call_reset:
            self._cancel_call_reset()
            self._cancel_call_reset = None

        if self.push:
            await self.push.async_stop()

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
            data[ATTR_UPDATE_STATE] = True
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

        if "gates" in response:
            for gate in response["gates"]:
                if (
                    ATTR_STREAM_URL in gate and ATTR_STREAM_URL_MPEG in gate
                ):  # pragma: no cover
                    gate[ATTR_STREAM_URL] = gate[ATTR_STREAM_URL_MPEG]

                for attr in [ATTR_STREAM_URL, ATTR_MUTE, ATTR_SIP_LOGIN]:
                    data[f"{gate['gate_id']}_{attr}"] = gate[attr]

                if gate["gate_id"] in self.intercoms:
                    continue

                self.code_map[gate["sip_login"]] = gate["gate_id"]

                self.intercoms[gate["gate_id"]] = IntercomEntityDescription(
                    id=gate["gate_id"],
                    key=str(gate["gate_id"]),
                    name=f"intercom_{gate['gate_id']}",
                    device_info=DeviceInfo(
                        identifiers={(DOMAIN, str(gate["gate_id"]))},
                        name=" ".join(
                            [
                                gate.get("gate_name"),
                            ]
                        ).strip(),
                        manufacturer=MAINTAINER,
                    ),
                )

                if self.new_intercom_callbacks:
                    async_dispatcher_send(
                        self.hass,
                        SIGNAL_NEW_INTERCOM,
                        self.intercoms[gate["gate_id"]],
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
            if not self.enable_sip:
                # Answering calls inside Home Assistant is optional: without a
                # SIP client the integration still reports call state from push
                # notifications, shows cameras and opens doors over the API.
                _LOGGER.debug("Built-in SIP client disabled, skipping VoIP start")

                return

            reg_expire_time: int | None = None
            with contextlib.suppress(TypeError, ValueError):
                if data.get(ATTR_SIP_REG_EXPIRE_TIME) is not None:
                    reg_expire_time = int(data[ATTR_SIP_REG_EXPIRE_TIME])

            self.voip = IntercomVoip(
                self.hass,
                data[ATTR_SIP_ADDRESS],
                data[ATTR_SIP_PORT],
                data[ATTR_SIP_LOGIN],
                data[ATTR_SIP_PASSWORD],
                self._call_callback,
                reg_expire_time=reg_expire_time,
            )

            self.hass.async_create_task(
                self._safe_voip_start()
            )

    async def _safe_voip_start(self) -> None:
        """Safely start VoIP with error logging."""

        try:
            await self.voip.safe_start(SIP_DEFAULT_RETRY)
        except Exception:
            _LOGGER.exception("Error starting VoIP")

    async def _call_callback(self, call: Call) -> None:  # pragma: no cover
        """Call callback

        :param call: Call
        """

        self.last_call = call

        self._set_call_state(call.state, call.login, {"call_id": call.call_id})

    @callback
    def _push_callback(self, data: dict[str, Any]) -> None:
        """Incoming push callback

        :param data: dict[str, Any]: Push payload (data section)
        """

        if data.get(ATTR_PUSH_CATEGORY) != PUSH_CATEGORY_START_CALL:
            _LOGGER.debug("Push ignored, category %r", data.get(ATTR_PUSH_CATEGORY))

            return

        # The panel is identified by "intercom_sip_login=<gate>" in the title.
        sip_login: str | None = None
        title: str = str(data.get(ATTR_PUSH_TITLE, ""))

        if "intercom_sip_login=" in title:
            sip_login = title.split("intercom_sip_login=")[-1].strip()

        self._set_call_state(
            CallState.RINGING,
            sip_login,
            {
                "call_id": data.get(ATTR_PUSH_CALL_ID),
                "transport": data.get(ATTR_PUSH_TRANSPORT),
                "source": "push",
            },
        )

    @callback
    def _set_call_state(
        self,
        state: CallState,
        login: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Update call state, notify entities and fire a bus event

        :param state: CallState: New state
        :param login: str | None: Panel sip login
        :param extra: dict[str, Any] | None: Extra event data
        """

        if self._cancel_call_reset:
            self._cancel_call_reset()
            self._cancel_call_reset = None

        if login:
            self.call_login = login

        # One visit can arrive twice — a push and then the SIP INVITE (or a
        # repeated push). The state is refreshed, but the event fires once.
        is_repeat: bool = state == self.call_state == CallState.RINGING

        self.call_state = state
        self.call_info = {
            ATTR_SIP_LOGIN: self.call_login,
            "gate_id": self.code_map.get(self.call_login or ""),
            "name": self._intercom_name(self.call_login),
            "state": state.value,
        } | (extra or {})

        async_dispatcher_send(self.hass, SIGNAL_CALL_STATE)

        events: dict[CallState, str] = {
            CallState.RINGING: EVENT_INCOMING_CALL,
            CallState.ANSWERED: EVENT_CALL_ANSWERED,
            CallState.ENDED: EVENT_CALL_ENDED,
        }

        if (event_type := events.get(state)) and not is_repeat:
            _LOGGER.debug("Firing %s: %r", event_type, self.call_info)

            self.hass.bus.async_fire(event_type, dict(self.call_info))

        if state == CallState.RINGING:
            # Nothing reports the end of the call when the SIP client is off.
            self._cancel_call_reset = event.async_call_later(
                self.hass, PUSH_CALL_TIMEOUT, self._call_timeout
            )

    @callback
    def _call_timeout(self, _now: Any) -> None:
        """Drop the ringing state when nothing else ended the call

        :param _now: Any
        """

        self._cancel_call_reset = None

        if self.call_state == CallState.RINGING:
            _LOGGER.debug("Call timed out, resetting state")

            self._set_call_state(CallState.ENDED)

    def _intercom_name(self, sip_login: str | None) -> str | None:
        """Human readable panel name

        :param sip_login: str | None
        :return str | None
        """

        gate_id: int | None = self.code_map.get(sip_login or "")

        if gate_id is None or gate_id not in self.intercoms:
            return None

        return self.intercoms[gate_id].device_info.get("name")


@dataclass(kw_only=True)
class IntercomEntityDescription(EntityDescription):
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
