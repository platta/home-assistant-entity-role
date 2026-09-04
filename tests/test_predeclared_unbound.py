"""Predeclared, unbound Entity Roles (PLAT-151).

Covers the migration pattern: declare a role's stable logical identity
(`role_id`, `name`) in Git with `source: null`/omitted before any physical
device is migrated into Home Assistant, then bind it later by adding
`source:` and reloading — without ever changing the role's entity identity.

Deliberately distinct from `tests/test_availability_unbound.py`, which
covers a role that *was* bound and then lost its source (an anomaly, flagged
with a repair issue) — this module covers a role that was simply never bound
yet (the expected, un-flagged migration state). Both conditions converge on
the same runtime shape (`source_entity_id is None`, `available is False`),
so several assertions here mirror that file's; what differs is the absence
of `ISSUE_UNBOUND` and the capability-contract fallback (see
entity.py::contract_intersect_iterable).
"""

from __future__ import annotations

import voluptuous as vol
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from custom_components.entity_role.const import (
    DOMAIN,
    ISSUE_UNBOUND,
    ISSUE_YAML_RECORD_INVALID,
)
from custom_components.entity_role.yaml_config import ROLE_SCHEMA, async_reconcile_yaml_roles

from .conftest import create_device, create_source_entity, role_entity_id

# --- ROLE_SCHEMA: unit-level coverage of the optional-source shapes --------


def test_role_schema_accepts_explicit_null_source() -> None:
    record = ROLE_SCHEMA(
        {"role_id": "office_ceiling", "role_domain": "light", "name": "Office Ceiling", "source": None}
    )
    assert record["source"] is None


def test_role_schema_accepts_omitted_source() -> None:
    record = ROLE_SCHEMA(
        {"role_id": "office_ceiling", "role_domain": "light", "name": "Office Ceiling"}
    )
    assert record["source"] is None


def test_role_schema_still_rejects_non_string_non_null_source() -> None:
    """Negative control: `source` accepts `None` specifically, not "anything"
    — a genuinely malformed value (e.g. a list) must still fail schema
    validation rather than silently becoming an unbound role."""
    with pytest.raises(vol.Invalid):
        ROLE_SCHEMA(
            {
                "role_id": "office_ceiling",
                "role_domain": "light",
                "name": "Office Ceiling",
                "source": ["not", "a", "string"],
            }
        )


# --- End-to-end: async_reconcile_yaml_roles ---------------------------------


async def test_predeclared_unbound_role_creates_single_unavailable_entity(
    hass: HomeAssistant,
) -> None:
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get("light.office_ceiling")
    assert state is not None
    assert state.state == "unavailable"
    assert state.attributes["friendly_name"] == "Office Ceiling"

    role_entities = [e for e in er.async_get(hass).entities.values() if e.platform == DOMAIN]
    assert len(role_entities) == 1


async def test_predeclared_unbound_role_omitted_source_key_same_as_null(
    hass: HomeAssistant,
) -> None:
    """The migration example in the ticket uses `source: null` explicitly,
    but an author may just as reasonably omit the key — both must produce
    the identical unbound role."""
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "office_ceiling", "role_domain": "light", "name": "Office Ceiling"}]},
    )
    await hass.async_block_till_done()

    state = hass.states.get("light.office_ceiling")
    assert state is not None
    assert state.state == "unavailable"


async def test_predeclared_unbound_role_raises_no_repair_issue(hass: HomeAssistant) -> None:
    """Predeclaring is the expected, intended migration state — distinct
    from ISSUE_UNBOUND (a previously-bound source that disappeared) and from
    ISSUE_YAML_RECORD_INVALID (a genuinely broken record). Neither should
    fire for a valid, merely-not-yet-bound role."""
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"{ISSUE_UNBOUND}_office_ceiling") is None
    assert registry.async_get_issue(DOMAIN, f"{ISSUE_YAML_RECORD_INVALID}_office_ceiling") is None


async def test_invalid_non_null_source_is_still_rejected(hass: HomeAssistant) -> None:
    """Negative control: optional `source` must not weaken validation of a
    genuinely present, invalid `source` — an unresolvable non-null reference
    still degrades that record exactly as before (design §10.1 R7), it does
    not silently become an accepted unbound role."""
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": "light.does_not_exist",
                }
            ]
        },
    )
    await hass.async_block_till_done()

    assert hass.states.get("light.office_ceiling") is None
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_YAML_RECORD_INVALID}_office_ceiling"
    )
    assert issue is not None


async def test_predeclared_role_capability_contract_advertised_while_unbound(
    hass: HomeAssistant,
) -> None:
    """The declared capability_contract is the intended role contract —
    advertised directly while unbound (nothing to intersect against yet),
    not collapsed to the bare on/off fallback."""
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                    "capability_contract": {
                        "supported_color_modes": ["color_temp", "hs"],
                        "supported_features": 0,
                    },
                }
            ]
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get("light.office_ceiling")
    assert state is not None
    assert set(state.attributes["supported_color_modes"]) == {"color_temp", "hs"}


async def test_predeclared_role_with_no_declared_contract_falls_back_to_onoff(
    hass: HomeAssistant,
) -> None:
    """Negative-control complement: a predeclared role that itself declares
    no color modes still falls back to the bare on/off mode, exactly like a
    bound role with an empty contract — the unbound fallback only ever
    reflects what was actually declared."""
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get("light.office_ceiling")
    assert state is not None
    assert set(state.attributes["supported_color_modes"]) == {"onoff"}


async def test_predeclared_role_binds_later_preserving_identity(hass: HomeAssistant) -> None:
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                }
            ]
        },
    )
    await hass.async_block_till_done()
    role_id = "light.office_ceiling"
    unique_id_before = er.async_get(hass).async_get(role_id).unique_id
    assert hass.states.get(role_id).state == "unavailable"

    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": source,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    # Same entity — bound in place, no new entity created for the migration.
    assert er.async_get(hass).async_get(role_id).unique_id == unique_id_before
    assert hass.states.get(role_id).state == "on"
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_UNBOUND}_office_ceiling") is None
    )


async def test_bound_role_can_be_unbound_via_yaml_edit(hass: HomeAssistant) -> None:
    """The reverse of the migration path: editing `source:` back to `null`
    unbinds a previously-bound role in place rather than removing it — only
    a role_id genuinely absent from the file is removed (see
    test_yaml_reconcile.py::test_yaml_removal_removes_the_role for that
    distinct case)."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": source,
                }
            ]
        },
    )
    await hass.async_block_till_done()
    role_id = "light.office_ceiling"
    unique_id_before = er.async_get(hass).async_get(role_id).unique_id

    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    assert hass.states.get(role_id) is not None
    assert hass.states.get(role_id).state == "unavailable"
    assert er.async_get(hass).async_get(role_id).unique_id == unique_id_before


# --- hide_source / device association while unbound -------------------------


async def test_predeclared_role_hide_source_is_a_noop_until_bound(hass: HomeAssistant) -> None:
    """hide_source has nothing to act on until a source exists — reconciling
    an unbound role with hide_source: true must not raise or touch any
    registry entry that doesn't exist yet."""
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                    "hide_source": True,
                }
            ]
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("light.office_ceiling").state == "unavailable"


async def test_predeclared_role_hides_source_once_bound(hass: HomeAssistant) -> None:
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                    "hide_source": True,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    assert er.async_get(hass).async_get(source).hidden_by is None

    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": source,
                    "hide_source": True,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(source).hidden_by == er.RegistryEntryHider.INTEGRATION


async def test_predeclared_role_has_no_device_link_until_bound(hass: HomeAssistant) -> None:
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                }
            ]
        },
    )
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get("light.office_ceiling").device_id is None


async def test_predeclared_role_links_to_source_device_once_bound(hass: HomeAssistant) -> None:
    device_id = create_device(hass, "office_hub")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": None,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    source = create_source_entity(hass, "light", "nanoleaf", state="on", device_id=device_id)
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_ceiling",
                    "role_domain": "light",
                    "name": "Office Ceiling",
                    "source": source,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get("light.office_ceiling").device_id == device_id


# --- cross-domain: predeclaring is not light-specific ------------------------


async def test_predeclared_unbound_switch_role_device_class_still_declared(
    hass: HomeAssistant,
) -> None:
    """switch/binary_sensor device_class is role-declared unconditionally
    (from_yaml_record sets it at construction regardless of binding state) —
    confirm predeclaring doesn't disturb that for a non-light domain."""
    from custom_components.entity_role.const import DOMAIN as ENTITY_ROLE_DOMAIN

    await async_reconcile_yaml_roles(
        hass,
        {
            ENTITY_ROLE_DOMAIN: [
                {
                    "role_id": "garage_outlet",
                    "role_domain": "switch",
                    "name": "Garage Outlet",
                    "source": None,
                    "device_class": "outlet",
                }
            ]
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get("switch.garage_outlet")
    assert state is not None
    assert state.state == "unavailable"
    assert state.attributes["device_class"] == "outlet"
