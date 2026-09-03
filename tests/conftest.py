"""Fixtures shared by the Entity Role test suite."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make custom_components/ discoverable, per the library's documented boilerplate."""
    yield


@pytest.fixture(autouse=True)
async def auto_setup_homeassistant_domain(hass: HomeAssistant):
    """Set up the core "homeassistant" domain before every test.

    In a real Home Assistant instance this is one of the first components
    bootstrap.py sets up, unconditionally, before any other integration
    (including custom ones) loads — so it is always present by the time this
    integration's entities are added. This test harness's `hass` fixture
    does *not* do that bootstrap step, unlike real HA. Without it,
    `hass.data[DATA_EXPOSED_ENTITIES]` (owned by this domain, per
    `homeassistant/components/homeassistant/__init__.py::async_setup`) is
    missing, and `RoleEntity._apply_hide_source_policy`'s call into
    `homeassistant.components.homeassistant.exposed_entities` raises a
    KeyError that (confirmed directly, PLAT-128) silently fails the whole
    entity add inside HA's own entity_platform — not a "migration skipped,
    everything else fine" degrade. Setting this up here matches real-world
    guarantees rather than adding a defensive fallback in production code for
    a condition that cannot occur outside this kind of minimal test harness.
    """
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.async_block_till_done()
    yield


def create_device(hass: HomeAssistant, identifier: str) -> str:
    """Register a standalone device and return its device_id.

    Used by device-linkage tests (PLAT-130) to give a source entity a real
    device to belong to. Devices always need *a* owning config entry, but
    not necessarily the same one as any entity that later links to it via
    `device_id` — that distinction (link vs. own) is the whole point of
    design §4's "the role never owns a device".
    """
    entry = MockConfigEntry(domain="demo_source")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("demo_source", identifier)},
    )
    return device.id


def create_source_entity(
    hass: HomeAssistant,
    domain: str,
    object_id: str,
    state: str = "on",
    attributes: dict | None = None,
    device_id: str | None = None,
) -> str:
    """Register a registry entry for a fake source entity and give it a state.

    Returns the entity_id. Used throughout the suite to stand in for a real
    hardware-backed entity (e.g. a Nanoleaf light) without depending on any
    concrete platform integration. `device_id` (see create_device), when
    given, links the source to an existing device — used by device-linkage
    tests (PLAT-130); omitted, the source has no device, matching every
    other test in this suite.
    """
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        domain,
        "demo_source",
        f"{object_id}_uid",
        suggested_object_id=object_id,
        device_id=device_id,
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
