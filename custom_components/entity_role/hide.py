"""Hide/unhide the wrapped source entity and migrate its voice-assistant
expose settings, mirroring switch_as_x's polish (design §2.1, §7, §10.1 R1).

Hiding uses entity_registry.async_update_entity(hidden_by=...), a long-stable
API verified in the design. Expose-setting migration uses the
homeassistant.components.homeassistant.exposed_entities helper where
importable; if that internal API's shape has moved, migration is skipped
with a logged warning rather than failing the create/rebind — hiding itself
still succeeds either way. Whether the import actually succeeds against the
CI-pinned HA version is recorded as a verify-in-CI item in the spike results
rather than claimed with confidence, since it could not be checked against
live core source in this sandbox.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)


def async_hide_source(hass: HomeAssistant, source_entity_id: str) -> None:
    registry = er.async_get(hass)
    if registry.async_get(source_entity_id) is None:
        return
    registry.async_update_entity(source_entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION)


def async_unhide_source(hass: HomeAssistant, source_entity_id: str) -> None:
    registry = er.async_get(hass)
    entry = registry.async_get(source_entity_id)
    if entry is None:
        return
    if entry.hidden_by == er.RegistryEntryHider.INTEGRATION:
        registry.async_update_entity(source_entity_id, hidden_by=None)


def async_migrate_expose_settings(
    hass: HomeAssistant, from_entity_id: str, to_entity_id: str
) -> bool:
    """Best-effort: copy voice-assistant expose flags from source to role.

    Returns True if migration ran, False if the internal expose-settings
    helper could not be imported/used on this HA version — callers treat
    False as "hide still applied, expose migration skipped", not an error.
    """
    try:
        from homeassistant.components.homeassistant import exposed_entities
    except ImportError:
        _LOGGER.warning(
            "Expose-settings migration skipped for %s -> %s: "
            "exposed_entities helper not importable on this HA version",
            from_entity_id,
            to_entity_id,
        )
        return False

    try:
        entities = exposed_entities.async_get(hass)
        for assistant in entities.async_listed_assistants():
            settings = entities.async_get_entity_settings(from_entity_id).get(assistant)
            if settings is not None:
                entities.async_expose_entity(
                    assistant, to_entity_id, settings.get("should_expose", True)
                )
        return True
    except Exception:  # noqa: BLE001 - see docstring: degrade, do not fail the rebind
        _LOGGER.warning(
            "Expose-settings migration skipped for %s -> %s: exposed_entities "
            "API shape did not match what this integration expected",
            from_entity_id,
            to_entity_id,
            exc_info=True,
        )
        return False
