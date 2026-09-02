"""Shared-architecture coverage for switch and binary_sensor roles (ticket
item 2: "enough switch/binary-sensor coverage to validate the shared
architecture" — design §9.2, §9.3).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_DEVICE_CLASS,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DOMAIN,
)

from .conftest import create_source_entity, role_entity_id


async def test_switch_role_proxies_and_keeps_role_declared_device_class(
    hass: HomeAssistant,
) -> None:
    source = create_source_entity(hass, "switch", "zigbee_plug", state="off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Workbench Outlet",
        data={CONF_ROLE_DOMAIN: "switch"},
        options={
            CONF_SOURCE: source,
            CONF_CAPABILITY_CONTRACT: {},
            CONF_DEVICE_CLASS: "outlet",
            "hide_source": False,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    role_id = role_entity_id(hass, "switch", entry.entry_id)
    state = hass.states.get(role_id)
    assert state.state == "off"
    assert state.attributes["device_class"] == "outlet"

    # Swap to hardware whose own integration reports no/different class —
    # the role's device_class does not change, since it is role-declared.
    replacement = create_source_entity(hass, "switch", "matter_plug", state="on")
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SOURCE: replacement}
    )
    await hass.async_block_till_done()

    state = hass.states.get(role_id)
    assert state.state == "on"
    assert state.attributes["device_class"] == "outlet"


async def test_binary_sensor_role_is_read_only_proxy(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "binary_sensor", "zigbee_contact", state="off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        data={CONF_ROLE_DOMAIN: "binary_sensor"},
        options={
            CONF_SOURCE: source,
            CONF_CAPABILITY_CONTRACT: {},
            CONF_DEVICE_CLASS: "door",
            "hide_source": False,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    role_id = role_entity_id(hass, "binary_sensor", entry.entry_id)
    assert hass.states.get(role_id).state == "off"
    assert hass.states.get(role_id).attributes["device_class"] == "door"

    hass.states.async_set(source, "on", {})
    await hass.async_block_till_done()
    assert hass.states.get(role_id).state == "on"
