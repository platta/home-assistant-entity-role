"""Repair fix-flow deep-link for an unbound UI-owned role (PLAT-128 carry-
forward item 4, previously UNVERIFIED/PARTIAL — design §10.2 #26).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DOMAIN,
    ISSUE_UNBOUND,
)
from custom_components.entity_role.repairs import ConfirmRepairFlow, async_create_fix_flow

from .conftest import create_source_entity, role_entity_id


async def _setup_unbound_ui_role(hass: HomeAssistant) -> tuple[MockConfigEntry, str]:
    source = create_source_entity(
        hass,
        "light",
        "nanoleaf",
        state="on",
        attributes={"supported_color_modes": ["hs"], "supported_features": 0},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={
            CONF_SOURCE: source,
            CONF_CAPABILITY_CONTRACT: {"supported_color_modes": ["hs"], "supported_features": 0},
            "hide_source": False,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    er.async_get(hass).async_remove(source)
    await hass.async_block_till_done()
    return entry, source


async def test_unbound_ui_role_issue_is_fixable(hass: HomeAssistant) -> None:
    entry, _ = await _setup_unbound_ui_role(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_UNBOUND}_{entry.entry_id}")
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.data == {"role_id": entry.entry_id, "entry_id": entry.entry_id}


async def test_fix_flow_rebinds_full_match_and_clears_issue(hass: HomeAssistant) -> None:
    entry, _ = await _setup_unbound_ui_role(hass)
    assert await async_setup_component(hass, "repairs", {})
    flow_manager = hass.data["repairs"]["flow_manager"]

    result = await flow_manager.async_init(
        DOMAIN, data={"issue_id": f"{ISSUE_UNBOUND}_{entry.entry_id}"}
    )
    assert result["step_id"] == "replace_hardware"

    replacement = create_source_entity(
        hass,
        "light",
        "hue",
        state="on",
        attributes={"supported_color_modes": ["hs"], "supported_features": 0},
    )
    result = await flow_manager.async_configure(
        result["flow_id"], {CONF_SOURCE: replacement}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_SOURCE] == replacement
    role_id = role_entity_id(hass, "light", entry.entry_id)
    assert hass.states.get(role_id).state == "on"
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_UNBOUND}_{entry.entry_id}") is None
    )


async def test_fix_flow_downgrade_requires_confirmation(hass: HomeAssistant) -> None:
    entry, _ = await _setup_unbound_ui_role(hass)
    assert await async_setup_component(hass, "repairs", {})
    flow_manager = hass.data["repairs"]["flow_manager"]

    result = await flow_manager.async_init(
        DOMAIN, data={"issue_id": f"{ISSUE_UNBOUND}_{entry.entry_id}"}
    )

    downgraded = create_source_entity(
        hass,
        "light",
        "cheap_bulb",
        state="on",
        attributes={"supported_color_modes": ["brightness"], "supported_features": 0},
    )
    result = await flow_manager.async_configure(
        result["flow_id"], {CONF_SOURCE: downgraded}
    )
    assert result["step_id"] == "confirm_downgrade"
    assert "hs" in result["description_placeholders"]["lost_capabilities"]

    result = await flow_manager.async_configure(result["flow_id"], {"confirm": True})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_SOURCE] == downgraded
    assert set(entry.options[CONF_CAPABILITY_CONTRACT]["supported_color_modes"]) == set()


async def test_yaml_owned_role_has_no_deep_link_fix_flow(hass: HomeAssistant) -> None:
    """A YAML-owned unbound role's issue carries entry_id=None (see
    RoleEntity._handle_source_unbound) — there is no config/options flow to
    deep-link into, so the fix flow falls back to the generic
    ConfirmRepairFlow rather than crashing on a missing entry."""
    flow = await async_create_fix_flow(hass, "irrelevant", {"role_id": "kitchen", "entry_id": None})
    assert isinstance(flow, ConfirmRepairFlow)
