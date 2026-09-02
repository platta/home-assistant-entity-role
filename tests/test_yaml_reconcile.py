"""Declarative (YAML) configuration path — spike gate (d).

Covers: create via YAML, reload without HA restart, rebind-in-place on
reload, a syntax-valid file with one bad record degrading only that role
(design §10.1 R7), and role removal via YAML.

The unparseable-file / top-level-schema-invalid "last-known-good" path is
handled one layer up, in __init__.py's reload service handler: when
homeassistant.helpers.reload.async_integration_yaml_config returns None,
async_reconcile_yaml_roles is never called at all, so every currently
running role is left exactly as it was. That contract is what this module's
async_reconcile_yaml_roles relies on — it only ever receives an
already-syntactically-valid config and is responsible solely for per-record
validity (schema_invalid, duplicate_role_id, unresolvable source) within it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from custom_components.entity_role.const import DOMAIN, ISSUE_YAML_RECORD_INVALID
from custom_components.entity_role.yaml_config import async_reconcile_yaml_roles

from .conftest import create_source_entity


async def test_yaml_role_created_and_reads_source_state(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "kitchen_counter",
                    "role_domain": "light",
                    "source": source,
                    "name": "Kitchen Counter",
                }
            ]
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get("light.kitchen_counter")
    assert state is not None
    assert state.state == "on"


async def test_yaml_reload_rebinds_in_place_without_restart(hass: HomeAssistant) -> None:
    source_a = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source_a}]},
    )
    await hass.async_block_till_done()
    role_entity_id = "light.kitchen_counter"
    unique_id_before = er.async_get(hass).async_get(role_entity_id).unique_id

    source_b = create_source_entity(hass, "light", "hue", state="off")
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source_b}]},
    )
    await hass.async_block_till_done()

    # Same entity_id/unique_id — reload updated the running role in place
    # rather than unloading and recreating it (design §10.2 #4's "candidate
    # refinement", adopted here as the implemented behavior for this spike).
    assert er.async_get(hass).async_get(role_entity_id).unique_id == unique_id_before
    assert hass.states.get(role_entity_id).state == "off"


async def test_yaml_removal_removes_the_role(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source}]},
    )
    await hass.async_block_till_done()
    assert hass.states.get("light.kitchen_counter") is not None

    await async_reconcile_yaml_roles(hass, {DOMAIN: []})
    await hass.async_block_till_done()
    assert hass.states.get("light.kitchen_counter") is None


async def test_bad_record_degrades_only_that_role(hass: HomeAssistant) -> None:
    """A syntax-valid file with one bad record: the good role still
    reconciles, the bad one is skipped and flagged, not the whole file
    rejected (design §10.1 R7)."""
    good_source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {"role_id": "kitchen_counter", "role_domain": "light", "source": good_source},
                {"role_id": "broken", "role_domain": "light", "source": "light.does_not_exist"},
            ]
        },
    )
    await hass.async_block_till_done()

    assert hass.states.get("light.kitchen_counter") is not None
    assert hass.states.get("light.broken") is None

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_YAML_RECORD_INVALID}_broken")
    assert issue is not None


async def test_record_becoming_valid_clears_its_issue(hass: HomeAssistant) -> None:
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {"role_id": "broken", "role_domain": "light", "source": "light.does_not_exist"}
            ]
        },
    )
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_YAML_RECORD_INVALID}_broken")
        is not None
    )

    fixed_source = create_source_entity(hass, "light", "hue", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "broken", "role_domain": "light", "source": fixed_source}]},
    )
    await hass.async_block_till_done()

    assert hass.states.get("light.broken") is not None
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_YAML_RECORD_INVALID}_broken") is None
    )


async def test_duplicate_role_id_only_first_record_accepted(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {"role_id": "dup", "role_domain": "light", "source": source},
                {"role_id": "dup", "role_domain": "light", "source": source},
            ]
        },
    )
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids("light")) == 1
