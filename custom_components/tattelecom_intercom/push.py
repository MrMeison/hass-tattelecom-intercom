"""Tattelecom Intercom push notifications.

The operator does not keep a permanent SIP registration for its subscribers:
when somebody rings an intercom panel it first sends a Firebase push
(``category=start_call``) and only then delivers the INVITE over SIP-over-TLS.
Registering a push token is therefore what makes incoming calls visible at all,
regardless of who answers them afterwards (this integration or a PBX trunk).

The token is obtained by emulating an Android device with the ``firebase-messaging``
library against the credentials of the official application.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .client import IntercomClient
from .const import (
    FIREBASE_API_KEY,
    FIREBASE_APP_ID,
    FIREBASE_PROJECT_ID,
    FIREBASE_SENDER_ID,
    STORAGE_KEY_FCM,
    STORAGE_VERSION,
)
from .exceptions import IntercomError

_LOGGER = logging.getLogger(__name__)

_FCM_HARDENED: bool = False


def _harden_fcm_client(client_cls: Any) -> None:
    """Work around two defects in firebase-messaging 0.4.5 (latest since 2025-05).

    Both were hit in production: the listener died seconds after ``Successfully
    logged in to MCS endpoint`` and stayed dead, so the operator's ``start_call``
    push never arrived and incoming calls were invisible — the SIP INVITE only
    follows the push, so a dead listener means a silent intercom while the
    integration itself looks perfectly healthy.

    1. ``_decrypt_raw_data`` base64-decodes ``crypto_key`` and ``salt`` taken from
       the incoming message headers *without* padding, while padding the client's
       own key material on the very next lines. base64url arrives unpadded, so any
       message whose field length is not a multiple of 4 raises
       ``binascii.Error: Incorrect padding``. Upstream knows: issue #40, and the
       fix in PR #37 is still unmerged.
    2. That exception propagates out of the message handler into ``_listen``, and
       the library shuts the whole client down. One malformed push therefore kills
       call delivery until Home Assistant is restarted. Worse, the acknowledgement
       is sent *after* the handler returns, so the message was never acked and the
       server redelivered it on every login — the failure did not heal itself.
       Swallowing it per-message keeps the listener alive and lets execution reach
       the ack, which drains the stuck message from the queue.

    Re-applied on every start but guarded by a flag, so reloading the config entry
    does not stack wrappers on top of each other. Patching private members is a
    calculated risk, hence the defensive lookups: if a future release renames them
    the integration must keep working unpatched rather than fail to start.
    """

    global _FCM_HARDENED  # pylint: disable=global-statement

    if _FCM_HARDENED:
        return

    original_decrypt: Any = getattr(client_cls, "_decrypt_raw_data", None)
    original_handle: Any = getattr(client_cls, "_handle_data_message", None)

    if original_decrypt is None or original_handle is None:  # pragma: no cover
        _LOGGER.debug(
            "Push: firebase-messaging internals changed, skipping the 0.4.x workaround"
        )

        return

    def _decrypt_raw_data_padded(
        credentials: dict, crypto_key_str: str, salt_str: str, raw_data: bytes
    ) -> bytes:
        """Restore the base64 padding the sender stripped."""

        def _pad(value: str) -> str:
            return value + "=" * (-len(value) % 4)

        return original_decrypt(credentials, _pad(crypto_key_str), _pad(salt_str), raw_data)

    def _handle_data_message_safe(self: Any, *args: Any, **kwargs: Any) -> Any:
        """Drop an undecodable push instead of taking the listener down with it."""

        try:
            return original_handle(self, *args, **kwargs)
        except Exception as _err:  # pylint: disable=broad-except
            _LOGGER.warning("Push: message dropped, listener kept alive: %r", _err)

            return None

    client_cls._decrypt_raw_data = staticmethod(  # pylint: disable=protected-access
        _decrypt_raw_data_padded
    )
    client_cls._handle_data_message = (  # pylint: disable=protected-access
        _handle_data_message_safe
    )

    _FCM_HARDENED = True

    _LOGGER.debug("Push: firebase-messaging hardened (padding + listener guard)")


class IntercomPush:
    """Intercom push client."""

    hass: HomeAssistant

    token: str | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        client: IntercomClient,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Initialize Intercom Push

        :param hass: HomeAssistant: Home Assistant object
        :param client: IntercomClient: Api client
        :param callback: Callable: Called with the push payload (data section)
        """

        self.hass = hass

        self._client = client
        self._callback = callback  # type: ignore

        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY_FCM)
        self._push_client: Any = None

        self.diagnostics: dict[str, Any] = {}

    async def async_start(self) -> bool:
        """Start push client

        :return bool: Is started
        """

        try:
            # Imported lazily: a missing optional dependency must not break the
            # rest of the integration (doors, cameras, streams keep working).
            from firebase_messaging import (  # pylint: disable=import-outside-toplevel
                FcmPushClient,
                FcmRegisterConfig,
            )

            _harden_fcm_client(FcmPushClient)
        except ImportError as _err:  # pragma: no cover
            _LOGGER.error(
                "Push notifications disabled, firebase-messaging is missing: %r", _err
            )

            return False

        credentials: dict | None = await self._store.async_load()

        _LOGGER.debug(
            "Push start: %s credentials", "restored" if credentials else "no stored"
        )

        self._push_client = FcmPushClient(
            self._on_notification,
            FcmRegisterConfig(
                project_id=FIREBASE_PROJECT_ID,
                app_id=FIREBASE_APP_ID,
                api_key=FIREBASE_API_KEY,
                messaging_sender_id=FIREBASE_SENDER_ID,
            ),
            credentials,
            self._on_credentials_updated,
            # Reuse the Home Assistant session: the library only closes sessions
            # it created itself.
            http_client_session=async_get_clientsession(self.hass),
        )

        try:
            self.token = await self._push_client.checkin_or_register()
        except Exception as _err:  # pylint: disable=broad-except
            _LOGGER.error("Push start: failed to obtain an FCM token: %r", _err)
            self._push_client = None

            return False

        await self.async_register_token()

        try:
            await self._push_client.start()
        except Exception as _err:  # pylint: disable=broad-except
            _LOGGER.error("Push start: failed to connect to FCM: %r", _err)
            self._push_client = None

            return False

        self.diagnostics["push_state"] = "started"

        _LOGGER.debug("Push start: listening, token %s", self._masked_token)

        return True

    async def async_stop(self) -> None:
        """Stop push client"""

        if not self._push_client:
            return

        try:
            await self._push_client.stop()
        except Exception as _err:  # pylint: disable=broad-except  # pragma: no cover
            _LOGGER.debug("Push stop: %r", _err)

        self._push_client = None
        self.diagnostics["push_state"] = "stopped"

        _LOGGER.debug("Push stop: listener stopped")

    async def async_register_token(self) -> bool:
        """Register the current token with the operator

        :return bool: Is registered
        """

        if not self.token:  # pragma: no cover
            return False

        try:
            response: dict = await self._client.update_push_token(self.token)
        except IntercomError as _err:
            _LOGGER.warning("Push: token registration failed: %r", _err)
            self.diagnostics["push_token_registered"] = False

            return False

        self.diagnostics["push_token_registered"] = bool(response.get("success", True))

        _LOGGER.debug(
            "Push: token %s registered, response %r", self._masked_token, response
        )

        return True

    @property
    def _masked_token(self) -> str:
        """Token for logs

        :return str
        """

        if not self.token:  # pragma: no cover
            return "<none>"

        return f"{self.token[:12]}…{self.token[-6:]}"

    def _on_credentials_updated(self, credentials: dict) -> None:
        """Persist rotated Firebase credentials

        :param credentials: dict: Firebase credentials
        """

        self.hass.async_create_task(self._store.async_save(credentials))

        token: str | None = (
            credentials.get("fcm", {}).get("registration", {}).get("token")
        )

        if token and token != self.token:
            _LOGGER.debug("Push: token rotated, re-registering")

            self.token = token

            self.hass.async_create_task(self.async_register_token())

    def _on_notification(
        self, notification: dict, persistent_id: str, context: Any = None
    ) -> None:
        """Handle an incoming push

        Called from the library task inside the Home Assistant event loop.

        :param notification: dict: Push message
        :param persistent_id: str: Message id
        :param context: Any: Callback context
        """

        data: dict = notification.get("data") or {}

        _LOGGER.debug("Push received (%s): %r", persistent_id, data)

        self.diagnostics["push_last"] = data

        try:
            self._callback(data)
        except Exception:  # pylint: disable=broad-except  # pragma: no cover
            _LOGGER.exception("Push: error in the incoming call callback")
