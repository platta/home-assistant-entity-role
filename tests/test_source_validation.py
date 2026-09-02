"""Bind-time source validation (helpers.async_validate_source).

Covers spike gate (g)'s static half — direct role-on-role bindings rejected
at validation — plus the domain-mismatch and not-found paths every
config/options/YAML flow relies on.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.entity_role.helpers import (
    SourceValidationError,
    async_resolve_source_ref,
    async_validate_source,
)

from .conftest import create_source_entity, registry_id_for


async def test_resolve_by_entity_id(hass: HomeAssistant) -> None:
    entity_id = create_source_entity(hass, "light", "kitchen")
    assert async_resolve_source_ref(hass, entity_id) == entity_id


async def test_resolve_by_registry_uuid(hass: HomeAssistant) -> None:
    entity_id = create_source_entity(hass, "light", "kitchen")
    uuid = registry_id_for(hass, entity_id)
    assert async_resolve_source_ref(hass, uuid) == entity_id


async def test_resolve_unknown_returns_none(hass: HomeAssistant) -> None:
    assert async_resolve_source_ref(hass, "light.does_not_exist") is None


async def test_validate_source_not_found(hass: HomeAssistant) -> None:
    with pytest.raises(SourceValidationError) as excinfo:
        async_validate_source(hass, "light", "light.does_not_exist")
    assert excinfo.value.args[0] == "source_not_found"


async def test_validate_domain_mismatch(hass: HomeAssistant) -> None:
    entity_id = create_source_entity(hass, "switch", "outlet")
    with pytest.raises(SourceValidationError) as excinfo:
        async_validate_source(hass, "light", entity_id)
    assert excinfo.value.args[0] == "domain_mismatch"


async def test_validate_rejects_direct_role_on_role(hass: HomeAssistant) -> None:
    """A source whose registry platform is entity_role itself is rejected —
    design §10.1 R3's static half of cycle safety."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    role_entry = registry.async_get_or_create(
        "light", "entity_role", "some_role_uid", suggested_object_id="some_role"
    )
    hass.states.async_set(role_entry.entity_id, "on", {})

    with pytest.raises(SourceValidationError) as excinfo:
        async_validate_source(hass, "light", role_entry.entity_id)
    assert excinfo.value.args[0] == "role_on_role_rejected"


async def test_validate_source_accepts_valid_match(hass: HomeAssistant) -> None:
    entity_id = create_source_entity(hass, "light", "kitchen")
    assert async_validate_source(hass, "light", entity_id) == entity_id
