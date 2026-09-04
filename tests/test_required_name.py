"""Required, non-blank `name` for declarative Entity Role records (PLAT-150).

Live validation during PLAT-134/PLAT-143 found that a declarative
(YAML-owned) role without its own explicit `name` fell back to a
machine-identity value in Home Assistant instead of showing a human-facing
display name — leaking the durable/replaceable identity split
(`role_id`/`name`/`source`, see design intent in yaml_config.py's module
docstring) through the abstraction. `ROLE_SCHEMA` (yaml_config.py) now makes
`name` required and rejects a blank/whitespace-only value; this module
covers both the schema-unit level (mirroring test_empty_yaml_config.py's own
two-level pattern) and the end-to-end reconcile path (mirroring
test_yaml_reconcile.py's `_RecordError`/repair-issue conventions).
"""

from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from custom_components.entity_role.const import DOMAIN, ISSUE_YAML_RECORD_INVALID
from custom_components.entity_role.yaml_config import ROLE_SCHEMA, async_reconcile_yaml_roles

from .conftest import create_source_entity

# --- ROLE_SCHEMA: unit-level coverage of the required-name validator -------


def test_role_schema_rejects_record_missing_name() -> None:
    with pytest.raises(vol.Invalid):
        ROLE_SCHEMA({"role_id": "kitchen_counter", "role_domain": "light", "source": "light.x"})


@pytest.mark.parametrize("blank_name", ["", "   ", "\t\n"])
def test_role_schema_rejects_blank_or_whitespace_only_name(blank_name: str) -> None:
    with pytest.raises(vol.Invalid):
        ROLE_SCHEMA(
            {
                "role_id": "kitchen_counter",
                "role_domain": "light",
                "source": "light.x",
                "name": blank_name,
            }
        )


def test_role_schema_accepts_a_genuine_name() -> None:
    """Negative-control complement to the two tests above: a real name must
    still pass — confirming the validator rejects blankness specifically,
    not `name` altogether."""
    record = ROLE_SCHEMA(
        {
            "role_id": "kitchen_counter",
            "role_domain": "light",
            "source": "light.x",
            "name": "Kitchen Counter",
        }
    )
    assert record["name"] == "Kitchen Counter"


# --- End-to-end: async_reconcile_yaml_roles ---------------------------------


async def test_yaml_record_missing_name_is_flagged_and_not_created(hass: HomeAssistant) -> None:
    """A record missing `name` degrades like any other invalid record (design
    §10.1 R7): it is not created, a repair issue is raised, and — critically
    — the role is never silently created under a fallback display name."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source}]},
    )
    await hass.async_block_till_done()

    assert hass.states.get("light.kitchen_counter") is None
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_YAML_RECORD_INVALID}_kitchen_counter"
    )
    assert issue is not None
    assert "name" in issue.translation_placeholders["reason"]


async def test_yaml_record_blank_name_is_flagged_and_not_created(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "kitchen_counter",
                    "role_domain": "light",
                    "source": source,
                    "name": "   ",
                }
            ]
        },
    )
    await hass.async_block_till_done()

    assert hass.states.get("light.kitchen_counter") is None
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_YAML_RECORD_INVALID}_kitchen_counter"
    )
    assert issue is not None


async def test_yaml_role_display_name_is_explicit_name_not_role_id(hass: HomeAssistant) -> None:
    """Positive control for the actual regression this ticket reports: the
    role's Home Assistant display name must be the declared `name`, and must
    not fall back to (or otherwise equal) the `role_id` machine-identity
    slug — the exact leak PLAT-134/PLAT-143 observed."""
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
    assert state.attributes["friendly_name"] == "Kitchen Counter"
    assert state.attributes["friendly_name"] != "kitchen_counter"

    registry_entry = er.async_get(hass).async_get("light.kitchen_counter")
    assert registry_entry.original_name == "Kitchen Counter"


async def test_yaml_role_first_creation_entity_id_is_role_id_not_slugified_name(
    hass: HomeAssistant,
) -> None:
    """Carry-forward finding from this ticket: before `name` was required,
    every record without one fell back to `name = role_id`, so Home
    Assistant's stock `suggested_object_id` (which slugifies `name`) always
    coincidentally produced `entity_id == role_id` on first creation. Now
    that `name` is a genuinely independent, human-chosen string, a `name`
    whose slug differs from `role_id` must still register under
    `<domain>.<role_id>` — the design's "YAML-owned role: an author-declared
    role_id slug" identity guarantee (see tests/test_identity.py) — not
    `<domain>.<slugified name>`. RoleEntity.suggested_object_id pins this
    explicitly for the YAML construction path; this is the regression test
    for that fix."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "office_light",
                    "role_domain": "light",
                    "source": source,
                    "name": "Family Room Light",
                }
            ]
        },
    )
    await hass.async_block_till_done()

    assert hass.states.get("light.office_light") is not None
    assert hass.states.get("light.family_room_light") is None
    registry_entry = er.async_get(hass).async_get("light.office_light")
    assert registry_entry is not None
    assert registry_entry.unique_id == "office_light"
    assert registry_entry.original_name == "Family Room Light"
