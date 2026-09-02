"""Binary sensor platform for Entity Role (design §9.3)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_DEVICE_CLASS,
    CONF_ROLE_ID,
    CONF_SOURCE,
    DOMAIN_BINARY_SENSOR,
)
from .entity import RoleEntity
from .helpers import async_resolve_source_ref


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([EntityRoleBinarySensor.from_config_entry(hass, entry)])


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    if discovery_info is None:
        return
    async_add_entities(
        [
            EntityRoleBinarySensor.from_yaml_record(hass, record)
            for record in discovery_info["roles"]
        ]
    )


class EntityRoleBinarySensor(RoleEntity, BinarySensorEntity):
    """A logical binary-sensor role (e.g. contact) proxying a bound source.

    Read-only: no commands to forward. device_class is role-declared (design
    §9.3, the `group` binary_sensor precedent), so the accessory type stays
    stable across a swap by construction.
    """

    @classmethod
    def from_config_entry(
        cls, hass: HomeAssistant, entry: ConfigEntry
    ) -> "EntityRoleBinarySensor":
        source_ref = entry.options.get(CONF_SOURCE)
        resolved = async_resolve_source_ref(hass, source_ref) if source_ref else None
        entity = cls(
            role_id=entry.entry_id,
            role_domain=DOMAIN_BINARY_SENSOR,
            name=entry.title,
            source_entity_id=resolved,
            contract=entry.options.get(CONF_CAPABILITY_CONTRACT, {}),
            source_ref=source_ref,
        )
        entity._attr_device_class = entry.options.get(CONF_DEVICE_CLASS)
        return entity

    @classmethod
    def from_yaml_record(
        cls, hass: HomeAssistant, record: dict[str, Any]
    ) -> "EntityRoleBinarySensor":
        source_ref = record.get(CONF_SOURCE)
        resolved = async_resolve_source_ref(hass, source_ref) if source_ref else None
        entity = cls(
            role_id=record[CONF_ROLE_ID],
            role_domain=DOMAIN_BINARY_SENSOR,
            name=record.get("name", record[CONF_ROLE_ID]),
            source_entity_id=resolved,
            contract=record.get(CONF_CAPABILITY_CONTRACT, {}),
            source_ref=source_ref,
        )
        entity._attr_device_class = record.get(CONF_DEVICE_CLASS)
        return entity

    @property
    def is_on(self) -> bool | None:
        if self.source_state is None:
            return None
        return self.source_state.state == "on"
