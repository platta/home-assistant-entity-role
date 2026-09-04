"""Device linkage (PLAT-130, design §4).

A role entity's registry device_id tracks whatever HA device its currently
bound source entity belongs to — so it appears on the physical device's
page, like switch_as_x — for both configuration sources, and stays correct
across rebind, source removal, and the source itself moving devices. The
role never creates or owns a device (design §4: "the role never owns a
device").
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DOMAIN,
)
from custom_components.entity_role.yaml_config import async_reconcile_yaml_roles

from .conftest import create_device, create_source_entity, role_entity_id


async def test_ui_role_linked_to_source_device_on_initial_bind(hass: HomeAssistant) -> None:
    device_id = create_device(hass, "kitchen_hub")
    source = create_source_entity(hass, "light", "nanoleaf", state="on", device_id=device_id)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={CONF_SOURCE: source, CONF_CAPABILITY_CONTRACT: {}, "hide_source": False},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    role_id = role_entity_id(hass, "light", entry.entry_id)
    assert er.async_get(hass).async_get(role_id).device_id == device_id


async def test_yaml_role_linked_to_source_device_on_initial_bind(hass: HomeAssistant) -> None:
    device_id = create_device(hass, "kitchen_hub")
    source = create_source_entity(hass, "light", "nanoleaf", state="on", device_id=device_id)
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source, "name": "Kitchen Counter"}]},
    )
    await hass.async_block_till_done()

    role_entry = er.async_get(hass).async_get("light.kitchen_counter")
    assert role_entry.device_id == device_id


async def test_rebind_relinks_to_new_source_device_identity_preserved(
    hass: HomeAssistant,
) -> None:
    device_a = create_device(hass, "device_a")
    device_b = create_device(hass, "device_b")
    source_a = create_source_entity(hass, "light", "nanoleaf", state="on", device_id=device_a)
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source_a, "name": "Kitchen Counter"}]},
    )
    await hass.async_block_till_done()
    role_id = "light.kitchen_counter"
    unique_id_before = er.async_get(hass).async_get(role_id).unique_id
    assert er.async_get(hass).async_get(role_id).device_id == device_a

    source_b = create_source_entity(hass, "light", "hue", state="on", device_id=device_b)
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source_b, "name": "Kitchen Counter"}]},
    )
    await hass.async_block_till_done()

    # Stable logical identity across rebind (design §4) — same unique_id/
    # entity_id — while the device linkage moved to the replacement source.
    assert er.async_get(hass).async_get(role_id).unique_id == unique_id_before
    assert er.async_get(hass).async_get(role_id).device_id == device_b


async def test_ui_rebind_relinks_to_new_source_device_identity_preserved(
    hass: HomeAssistant,
) -> None:
    """The UI rebind path is structurally different from YAML's: an options
    change reloads the whole config entry, tearing this entity down and
    constructing a *new* instance from the updated options (config_flow.py's
    module docstring) — it never calls async_rebind at all. Device linkage
    must therefore also be correct via async_added_to_hass's initial-bind
    path, not only async_rebind's, for a role that is being rebound rather
    than created for the first time."""
    device_a = create_device(hass, "device_a")
    device_b = create_device(hass, "device_b")
    source_a = create_source_entity(hass, "light", "nanoleaf", state="on", device_id=device_a)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={CONF_SOURCE: source_a, CONF_CAPABILITY_CONTRACT: {}, "hide_source": False},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    role_id = role_entity_id(hass, "light", entry.entry_id)
    unique_id_before = er.async_get(hass).async_get(role_id).unique_id
    assert er.async_get(hass).async_get(role_id).device_id == device_a

    source_b = create_source_entity(hass, "light", "hue", state="on", device_id=device_b)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SOURCE: source_b}
    )
    await hass.async_block_till_done()

    assert role_entity_id(hass, "light", entry.entry_id) == role_id
    assert er.async_get(hass).async_get(role_id).unique_id == unique_id_before
    assert er.async_get(hass).async_get(role_id).device_id == device_b


async def test_source_without_device_role_stays_unlinked_no_fabricated_device(
    hass: HomeAssistant,
) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="on")  # no device
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source, "name": "Kitchen Counter"}]},
    )
    await hass.async_block_till_done()

    role_entry = er.async_get(hass).async_get("light.kitchen_counter")
    assert role_entry.device_id is None
    # This integration itself never calls device_registry.async_get_or_create
    # (see entity.py's _sync_device_link docstring) — confirm nothing was
    # fabricated for the role's own registry entry to co-own.
    assert len(dr.async_get(hass).devices) == 0


async def test_source_removed_detaches_device_link_role_preserved(hass: HomeAssistant) -> None:
    device_id = create_device(hass, "kitchen_hub")
    source = create_source_entity(hass, "light", "nanoleaf", state="on", device_id=device_id)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={CONF_SOURCE: source, CONF_CAPABILITY_CONTRACT: {}, "hide_source": False},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    role_id = role_entity_id(hass, "light", entry.entry_id)
    assert er.async_get(hass).async_get(role_id).device_id == device_id

    er.async_get(hass).async_remove(source)
    await hass.async_block_till_done()

    # The role survives (design §8's survive-not-delete policy) with its
    # device linkage safely cleared, not dangling on a removed source.
    assert hass.states.get(role_id) is not None
    assert er.async_get(hass).async_get(role_id).device_id is None


async def test_source_device_move_updates_role_linkage(hass: HomeAssistant) -> None:
    device_a = create_device(hass, "device_a")
    device_b = create_device(hass, "device_b")
    source = create_source_entity(hass, "light", "nanoleaf", state="on", device_id=device_a)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={CONF_SOURCE: source, CONF_CAPABILITY_CONTRACT: {}, "hide_source": False},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    role_id = role_entity_id(hass, "light", entry.entry_id)
    assert er.async_get(hass).async_get(role_id).device_id == device_a

    # The source's own entity_id is unchanged — only its device — the case
    # _handle_registry_event's "unrelated" branch must still resync (see its
    # docstring).
    er.async_get(hass).async_update_entity(source, device_id=device_b)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(role_id).device_id == device_b
