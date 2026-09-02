"""Source unavailable/removal behavior (design §8, spike gate c).

The role must survive source removal — go unavailable, keep its identity,
raise a repair issue — rather than being deleted, and must recover cleanly
on rebind.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DOMAIN,
    ISSUE_UNBOUND,
)

from .conftest import create_source_entity


async def test_source_goes_unavailable_role_mirrors(hass: HomeAssistant) -> None:
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
    role_entity_id = hass.states.async_entity_ids("light")[0]

    hass.states.async_set(source, "unavailable", {})
    await hass.async_block_till_done()
    assert hass.states.get(role_entity_id).state == "unavailable"


async def test_source_removed_from_registry_role_survives_unbound(hass: HomeAssistant) -> None:
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
    role_entity_id = hass.states.async_entity_ids("light")[0]
    unique_id_before = er.async_get(hass).async_get(role_entity_id).unique_id

    er.async_get(hass).async_remove(source)
    await hass.async_block_till_done()

    # The role entity still exists, is unavailable, and kept its identity —
    # it was not deleted (unlike switch_as_x's chosen policy).
    assert hass.states.get(role_entity_id) is not None
    assert hass.states.get(role_entity_id).state == "unavailable"
    assert er.async_get(hass).async_get(role_entity_id).unique_id == unique_id_before

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_UNBOUND}_{entry.entry_id}")
    assert issue is not None


async def test_rebind_after_removal_clears_issue_and_recovers(hass: HomeAssistant) -> None:
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
    role_entity_id = hass.states.async_entity_ids("light")[0]

    er.async_get(hass).async_remove(source)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_UNBOUND}_{entry.entry_id}") is not None

    replacement = create_source_entity(hass, "light", "hue", state="on")
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SOURCE: replacement}
    )
    await hass.async_block_till_done()

    assert hass.states.async_entity_ids("light") == [role_entity_id]
    assert hass.states.get(role_entity_id).state == "on"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_UNBOUND}_{entry.entry_id}") is None
