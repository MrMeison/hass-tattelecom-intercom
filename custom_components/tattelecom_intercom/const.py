"""Constants for the Tattelecom Intercom integration."""
from __future__ import annotations

from typing import Final

from aiohttp.hdrs import ACCEPT, ACCEPT_CHARSET, ACCEPT_ENCODING, USER_AGENT
from homeassistant.const import Platform

# fmt: off
DOMAIN: Final = "tattelecom_intercom"
"""Integration domain."""

NAME: Final = "Tattelecom Intercom"
"""Integration name."""

MAINTAINER: Final = "Tattelecom"
ATTRIBUTION: Final = "Data provided by Tattelecom Intercom"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.CAMERA,
    Platform.MEDIA_PLAYER,
]

"""Diagnostic const"""
DIAGNOSTIC_DATE_TIME: Final = "date_time"
DIAGNOSTIC_MESSAGE: Final = "message"
DIAGNOSTIC_CONTENT: Final = "content"

"""Helper const"""
UPDATER: Final = "updater"
UPDATE_LISTENER: Final = "update_listener"
OPTION_IS_FROM_FLOW: Final = "is_from_flow"

SIGNAL_NEW_INTERCOM: Final = f"{DOMAIN}-new-intercom"
SIGNAL_SIP_STATE: Final = f"{DOMAIN}-sip-state"
SIGNAL_CALL_STATE: Final = f"{DOMAIN}-call-state"

CONF_PHONE: Final = "phone"
CONF_SMS_CODE: Final = "sms_code"
CONF_ENABLE_SIP: Final = "enable_sip"

"""Events on the Home Assistant bus"""
EVENT_INCOMING_CALL: Final = f"{DOMAIN}_incoming_call"
EVENT_CALL_ANSWERED: Final = f"{DOMAIN}_call_answered"
EVENT_CALL_ENDED: Final = f"{DOMAIN}_call_ended"

PHONE_MIN: Final = 70000000000
PHONE_MAX: Final = 79999999999
SMS_CODE_LENGTH: Final = 6

"""Default settings"""
DEFAULT_SCAN_INTERVAL: Final = 3600
MIN_SCAN_INTERVAL: Final = 600
DEFAULT_TIMEOUT: Final = 10
DEFAULT_CALL_DELAY: Final = 1
DEFAULT_SLEEP: Final = 3
DEFAULT_RETRY: Final = 10
# The built-in SIP client registers over UDP on the port reported by
# subscriber/sipsettings (9740) — calls are never delivered there: the operator
# rings SIP-over-TLS on 9741 after an FCM push. Keep it off unless the user
# explicitly wants the legacy client (a PBX trunk handles calls here).
DEFAULT_ENABLE_SIP: Final = False

"""Tattelecom intercom API client const"""
CLIENT_URL: Final = "https://domofon.tattelecom.ru/{api_version}/{path}"
HEADERS: Final = {
    ACCEPT: "application/json",
    ACCEPT_CHARSET: "UTF-8",
    USER_AGENT: "ktor-client",
    ACCEPT_ENCODING: "gzip",
}
DEVICE_CODE: Final = "Android_empty_push_token"
DEVICE_OS: Final = 1

"""Push notifications (FCM)

The operator wakes subscribers up with a Firebase push before ringing them over
SIP. The token is registered with subscriber/update-push-token — the request
carries the raw FCM token only, there is no device_code in it (verified against
the decompiled app and on the wire, 2026-07-31).
"""
PUSH_SERVICE_FCM: Final = "fcm"
PUSH_CATEGORY_START_CALL: Final = "start_call"
# A push announces a call but never its end, and without the built-in SIP client
# there is no BYE to observe either — the ringing state is dropped on a timer.
# The panel gives up ringing well before this.
PUSH_CALL_TIMEOUT: Final = 60

FIREBASE_PROJECT_ID: Final = "israeldidnothingwrong-80a00"
FIREBASE_APP_ID: Final = "1:49573252933:android:d686dc8f406db347a4382c"
FIREBASE_API_KEY: Final = "AIzaSyDvjcS4tcZo2Y3u4bdwcPTxAMn9USEHE1E"
FIREBASE_SENDER_ID: Final = "49573252933"

# Firebase device credentials have to survive restarts: re-registering produces
# a new token every time, and the operator would keep pushing to the stale one.
STORAGE_VERSION: Final = 1
STORAGE_KEY_FCM: Final = f"{DOMAIN}_fcm"

"""Attributes"""
ATTR_UPDATE_STATE: Final = "update_state"
ATTR_UPDATE_STATE_NAME: Final = "Update state"

ATTR_SIP_ADDRESS: Final = "sip_address"
ATTR_SIP_LOGIN: Final = "sip_login"
ATTR_SIP_PASSWORD: Final = "sip_password"
ATTR_SIP_PORT: Final = "sip_port"
ATTR_SIP_REG_EXPIRE_TIME: Final = "reg_expire_time"

ATTR_STREAM_URL: Final = "stream_url"
ATTR_STREAM_URL_MPEG: Final = "stream_url_mpeg"
ATTR_MUTE: Final = "mute"

"""Attributes sensor"""
SENSOR_SIP_STATE: Final = "sip_state"
SENSOR_SIP_STATE_NAME: Final = "Sip state"

SENSOR_CALL_STATE: Final = "call_state"
SENSOR_CALL_STATE_NAME: Final = "Call state"

"""Attributes camera"""
CAMERA_NAME: Final = "Camera"

CAMERA_INCOMING: Final = "incoming"
CAMERA_INCOMING_NAME: Final = "Incoming"

"""Attributes media player"""
MEDIA_PLAYER_OUTGOING: Final = "outgoing"
MEDIA_PLAYER_OUTGOING_NAME: Final = "Outgoing"

"""Attributes button"""
BUTTON_OPEN: Final = "open_door"
BUTTON_OPEN_NAME: Final = "Open door"

BUTTON_ANSWER: Final = "answer"
BUTTON_ANSWER_NAME: Final = "Answer"

BUTTON_DECLINE: Final = "decline"
BUTTON_DECLINE_NAME: Final = "Decline"

BUTTON_HANGUP: Final = "hangup"
BUTTON_HANGUP_NAME: Final = "Hangup"

"""Attributes switch"""
SWITCH_MUTE_NAME: Final = "Mute"

"""Push payload attributes"""
ATTR_PUSH_CATEGORY: Final = "category"
ATTR_PUSH_TITLE: Final = "title"
ATTR_PUSH_CALL_ID: Final = "sip_call_id"
ATTR_PUSH_TRANSPORT: Final = "sip_transport"

"""VoIP"""
SIP_PORT: Final = 60266
# Calls arrive over TLS on 9741; subscriber/sipsettings advertises 9740/UDP,
# which never receives an INVITE.
SIP_TLS_PORT: Final = 9741

TAG_REGISTER: Final = "register"
TAG_DEREGISTER: Final = "deregister"
SIP_EXPIRES: Final = 3600
SIP_TIMEOUT: Final = 10
SIP_PING_TIMEOUT: Final = 10
SIP_RETRY_SLEEP: Final = 5
SIP_DEFAULT_RETRY: Final = 10
SIP_USER_AGENT: Final = "Unknown (belle-sip/4.4.0)"
VOIP_CLEAN_DELAY: Final = 1800

PHONE_EVENT_KEYS: Final = (
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "*",
    "#",
    "A",
    "B",
    "C",
    "D",
)
