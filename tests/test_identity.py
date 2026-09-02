"""Stable logical identity across reload/restart, for both configuration
sources (ticket item: "stable identity across reload/restart"; design §4).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DOMAIN,
)
from custom_components.entity_role.yaml_config import async_reconcile_yaml_roles

from .conftest import create_source_entity, role_entity_id as get_role_entity_id


async def test_ui_owned_role_unique_id_is_the_config_entry_id(hass: HomeAssistant) -> None:
    """design §4: "UI-owned role: the config entry ID" — the switch_as_x
    pattern."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={CONF_SOURCE: source, CONF_CAPABILITY_CONTRACT: {}, "hide_source": False},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    role_id = get_role_entity_id(hass, "light", entry.entry_id)
    assert er.async_get(hass).async_get(role_id).unique_id == entry.entry_id


async def test_ui_owned_role_survives_unload_reload_with_same_identity(
    hass: HomeAssistant,
) -> None:
    """Simulates a config-entry reload (the same primitive an HA restart
    drives): unique_id is unchanged."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={CONF_SOURCE: source, CONF_CAPABILITY_CONTRACT: {}, "hide_source": False},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    role_id = get_role_entity_id(hass, "light", entry.entry_id)
    unique_id_before = er.async_get(hass).async_get(role_id).unique_id

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert get_role_entity_id(hass, "light", entry.entry_id) == role_id
    assert er.async_get(hass).async_get(role_id).unique_id == unique_id_before


async def test_yaml_owned_role_unique_id_is_the_declared_role_id(hass: HomeAssistant) -> None:
    """design §4: "YAML-owned role: an author-declared role_id slug"."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source}]},
    )
    await hass.async_block_till_done()

    assert (
        er.async_get(hass).async_get("light.kitchen_counter").unique_id == "kitchen_counter"
    )


async def test_yaml_owned_role_identity_stable_across_simulated_restart(
    hass: HomeAssistant,
) -> None:
    """Simulates an HA restart for the declarative path: tear down every
    running role (as unload-on-stop would) and re-apply the same file from
    a cold reconcile — unique_id/entity_id converge to the same values,
    since YAML-owned identity is author-declared and lives in the file
    itself (design §6.3: "bindings converge to Git with no dependence on
    .storage")."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    config = {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source}]}

    await async_reconcile_yaml_roles(hass, config)
    await hass.async_block_till_done()
    unique_id_before = er.async_get(hass).async_get("light.kitchen_counter").unique_id

    await async_reconcile_yaml_roles(hass, {DOMAIN: []})
    await hass.async_block_till_done()
    assert hass.states.get("light.kitchen_counter") is None

    await async_reconcile_yaml_roles(hass, config)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get("light.kitchen_counter").unique_id == unique_id_before
