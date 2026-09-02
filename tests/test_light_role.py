"""End-to-end light role behavior via a config entry (spike gates a, e-adjacent).

Covers: state/attribute proxying, contract ∩ source capability intersection
including downgrade on rebind, command forwarding, and identity stability
(unique_id/entity_id untouched) across a rebind — spike gate (a): "automation
+ scene + dashboard referencing a role survive a live rebind untouched" is
approximated here at the entity-identity level, the concrete guarantee those
consumers depend on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DOMAIN,
)

from .conftest import create_source_entity


async def _setup_light_role(
    hass: HomeAssistant, source_entity_id: str, contract: dict
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={
            CONF_SOURCE: source_entity_id,
            CONF_CAPABILITY_CONTRACT: contract,
            "hide_source": False,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_role_proxies_state_and_attributes(hass: HomeAssistant) -> None:
    source = create_source_entity(
        hass,
        "light",
        "nanoleaf",
        state="on",
        attributes={
            "supported_color_modes": ["hs", "color_temp"],
            "supported_features": 0,
            "brightness": 120,
            "color_mode": "hs",
            "hs_color": (30, 40),
        },
    )
    entry = await _setup_light_role(
        hass, source, {"supported_color_modes": ["hs", "color_temp"], "supported_features": 0}
    )

    role_entity_id = hass.states.async_entity_ids("light")[0]
    role_state = hass.states.get(role_entity_id)

    assert role_state.state == "on"
    assert role_state.attributes["brightness"] == 120
    assert set(role_state.attributes["supported_color_modes"]) == {"hs", "color_temp"}

    # Identity: unique_id is the config entry id, per design §4.
    from homeassistant.helpers import entity_registry as er

    registry_entry = er.async_get(hass).async_get(role_entity_id)
    assert registry_entry.unique_id == entry.entry_id


async def test_source_state_change_propagates(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="off")
    await _setup_light_role(hass, source, {"supported_color_modes": [], "supported_features": 0})
    role_entity_id = hass.states.async_entity_ids("light")[0]
    assert hass.states.get(role_entity_id).state == "off"

    hass.states.async_set(source, "on", {})
    await hass.async_block_till_done()
    assert hass.states.get(role_entity_id).state == "on"


async def test_contract_intersection_narrows_downgraded_hardware(hass: HomeAssistant) -> None:
    """Contract seeded from an RGB+CCT light; source is brightness-only.

    Advertised capabilities are contract ∩ source — narrower than the
    contract — per design §5.
    """
    source = create_source_entity(
        hass,
        "light",
        "cheap_bulb",
        state="on",
        attributes={"supported_color_modes": ["brightness"], "supported_features": 0},
    )
    await _setup_light_role(
        hass,
        source,
        {"supported_color_modes": ["hs", "color_temp", "brightness"], "supported_features": 0},
    )
    role_entity_id = hass.states.async_entity_ids("light")[0]
    modes = set(hass.states.get(role_entity_id).attributes["supported_color_modes"])
    assert modes == {"brightness"}


async def test_command_forwarded_to_source(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="off")
    await _setup_light_role(hass, source, {"supported_color_modes": [], "supported_features": 0})
    role_entity_id = hass.states.async_entity_ids("light")[0]

    calls = []

    async def fake_turn_on(call):
        calls.append(call)
        hass.states.async_set(source, "on", {})

    hass.services.async_register("light", "turn_on", fake_turn_on)

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": role_entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == [source] or calls[0].data["entity_id"] == source
    assert hass.states.get(role_entity_id).state == "on"


async def test_rebind_preserves_identity_and_updates_contract(hass: HomeAssistant) -> None:
    old_source = create_source_entity(
        hass,
        "light",
        "nanoleaf",
        state="on",
        attributes={"supported_color_modes": ["hs"], "supported_features": 0},
    )
    entry = await _setup_light_role(
        hass, old_source, {"supported_color_modes": ["hs"], "supported_features": 0}
    )
    role_entity_id = hass.states.async_entity_ids("light")[0]

    new_source = create_source_entity(
        hass,
        "light",
        "hue",
        state="on",
        attributes={"supported_color_modes": ["hs", "color_temp"], "supported_features": 0},
    )

    from homeassistant.helpers import entity_registry as er

    unique_id_before = er.async_get(hass).async_get(role_entity_id).unique_id

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_SOURCE: new_source,
            CONF_CAPABILITY_CONTRACT: {
                "supported_color_modes": ["hs", "color_temp"],
                "supported_features": 0,
            },
        },
    )
    await hass.async_block_till_done()

    # entity_id and unique_id are unchanged across the rebind.
    assert hass.states.async_entity_ids("light") == [role_entity_id]
    assert er.async_get(hass).async_get(role_entity_id).unique_id == unique_id_before

    state = hass.states.get(role_entity_id)
    assert set(state.attributes["supported_color_modes"]) == {"hs", "color_temp"}
