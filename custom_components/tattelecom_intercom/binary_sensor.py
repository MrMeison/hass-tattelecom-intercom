"""Binary sensor component."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_UPDATE_STATE, ATTR_UPDATE_STATE_NAME
from .entity import IntercomEntity
from .updater import IntercomUpdater, async_get_updater

PARALLEL_UPDATES = 0

BINARY_SENSORS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key=ATTR_UPDATE_STATE,
        name=ATTR_UPDATE_STATE_NAME,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,
    ),
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Intercom binary sensor entry.

    :param hass: HomeAssistant: Home Assistant object
    :param config_entry: ConfigEntry: Config Entry object
    :param async_add_entities: AddEntitiesCallback: Async add callback
    """

    updater: IntercomUpdater = async_get_updater(hass, config_entry.entry_id)

    entities: list[IntercomBinarySensor] = [
        IntercomBinarySensor(
            f"{config_entry.entry_id}-{description.key}",
            description,
            updater,
        )
        for description in BINARY_SENSORS
    ]
    async_add_entities(entities)


# pylint: disable=too-many-ancestors
class IntercomBinarySensor(IntercomEntity, BinarySensorEntity):
    """Intercom binary sensor."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        unique_id: str,
        description: BinarySensorEntityDescription,
        updater: IntercomUpdater,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(unique_id, description, updater, ENTITY_ID_FORMAT)
        
        self._attr_is_on = bool(updater.data.get(description.key, False))

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self._attr_is_on

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        is_on = bool(self.coordinator.data.get(self.entity_description.key, False))
        if self._attr_is_on != is_on:
            self._attr_is_on = is_on
            self.async_write_ha_state()
