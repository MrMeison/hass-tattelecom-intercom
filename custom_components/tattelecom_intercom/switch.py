"""Switch component."""


from __future__ import annotations

import logging
from typing import Any, Final

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
    ENTITY_ID_FORMAT,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_MUTE, SIGNAL_NEW_INTERCOM, SWITCH_MUTE_NAME
from .entity import IntercomEntity
from .exceptions import IntercomError
from .updater import IntercomEntityDescription, IntercomUpdater, async_get_updater

PARALLEL_UPDATES = 0

ICONS: Final = {
    STATE_ON: "mdi:bell-off",
    STATE_OFF: "mdi:bell",
}

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tattelecom intercom switch entry.

    :param hass: HomeAssistant: Home Assistant object
    :param config_entry: ConfigEntry: ConfigEntry object
    :param async_add_entities: AddEntitiesCallback: AddEntitiesCallback callback object
    """

    updater: IntercomUpdater = async_get_updater(hass, config_entry.entry_id)

    @callback
    def add_switch(entity: IntercomEntityDescription) -> None:
        """Add switch.

        :param entity: IntercomEntityDescription: Sensor object
        """

        async_add_entities(
            [
                IntercomSwitch(
                    f"{config_entry.entry_id}-switch-{entity.id}",
                    entity,
                    updater,
                )
            ]
        )

    for intercom in updater.intercoms.values():
        add_switch(intercom)

    updater.new_intercom_callbacks.append(
        async_dispatcher_connect(hass, SIGNAL_NEW_INTERCOM, add_switch)
    )


# pylint: disable=too-many-ancestors
class IntercomSwitch(IntercomEntity, SwitchEntity):
    """Intercom switch."""

    entity_description: SwitchEntityDescription

    def __init__(
        self,
        unique_id: str,
        description: SwitchEntityDescription,
        updater: IntercomUpdater,
    ) -> None:
        """Initialize switch."""
        super().__init__(unique_id, description, updater, ENTITY_ID_FORMAT)

        self._attr_is_on = bool(updater.data.get(f"{description.key}_{ATTR_MUTE}", False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        try:
            await self._updater.client.mute(int(self.entity_description.key))
            self._attr_is_on = True
            self._updater.update_data(f"{self.entity_description.key}_{ATTR_MUTE}", True)
        except IntercomError as err:
            _LOGGER.error("Failed to turn on: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        try:
            await self._updater.client.unmute(int(self.entity_description.key))
            self._attr_is_on = False
            self._updater.update_data(f"{self.entity_description.key}_{ATTR_MUTE}", False)
        except IntercomError as err:
            _LOGGER.error("Failed to turn off: %s", err)
        self.async_write_ha_state()

    def _change_icon(self, is_on: bool) -> None:
        """Change icon

        :param is_on: bool
        """

        icon_name: str = STATE_ON if is_on else STATE_OFF

        if icon_name in ICONS:
            self._attr_icon = ICONS[icon_name]
