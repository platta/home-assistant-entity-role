"""Fixtures shared by the Entity Role test suite."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make custom_components/ discoverable, per the library's documented boilerplate."""
    yield


def create_source_entity(
    hass: HomeAssistant,
    domain: str,
    object_id: str,
    state: str = "on",
    attributes: dict | None = None,
) -> str:
    """Register a registry entry for a fake source entity and give it a state.

    Returns the entity_id. Used throughout the suite to stand in for a real
    hardware-backed entity (e.g. a Nanoleaf light) without depending on any
    concrete platform integration.
    """
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        domain, "demo_source", f"{object_id}_uid", suggested_object_id=object_id
    )
    hass.states.async_set(entry.entity_id, state, attributes or {})
    return entry.entity_id


def registry_id_for(hass: HomeAssistant, entity_id: str) -> str:
    """Return the entity-registry UUID (RegistryEntry.id) for entity_id."""
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None
    return entry.id


def role_entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    """Return a role's entity_id looked up by its unique_id (the config
    entry id for a UI-owned role, the role_id for a YAML-owned one).

    Deliberately not `hass.states.async_entity_ids(domain)[0]`: a test that
    leaves the source unhidden has *two* entities in the same domain (the
    role and its source), and indexing is ambiguous between them — this
    spike's own first CI run caught exactly that test-authoring bug.
    """
    from custom_components.entity_role.const import DOMAIN

    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id
