"""Hide/unhide the wrapped source entity and migrate its voice-assistant
expose settings, mirroring switch_as_x's polish (design §2.1, §7, §10.1 R1).

Hiding uses entity_registry.async_update_entity(hidden_by=...), a long-stable
API verified in the design.

PLAT-128 carry-forward item 3 ("replace or validate the best-effort
expose-settings migration against current supported HA APIs"): the spike's
original implementation guessed at an object-returning
`exposed_entities.async_get(hass)` shape it could not verify. This pass
installed a real, current homeassistant package
(`homeassistant/components/homeassistant/exposed_entities.py`, verified
directly, package version 2025.1.4 — the newest release resolvable in this
sandbox's package index, see the repository README's environment-constraints
note) and read `switch_as_x`'s own `copy_expose_settings` (`switch_as_x/
entity.py::BaseEntity.async_added_to_hass`) as the precedent this integration
already claims to mirror. The real API is a set of module-level functions
taking `hass` explicitly, not an object returned by `async_get`:
`async_get_entity_settings(hass, entity_id) -> dict[str, Mapping[str, Any]]`
(keyed by assistant, e.g. "conversation") and
`async_expose_entity(hass, assistant, entity_id, should_expose)`. There is no
`async_listed_assistants()` method; `switch_as_x` iterates
`async_get_entity_settings(...).items()` directly and skips any assistant
with no explicit `should_expose` recorded — the same approach used below.
The previous guessed shape does not exist on any HA version new enough to
matter and would have silently no-opped via the broad except every time.

The import is still wrapped in try/except ImportError as defense-in-depth
(this remains an internal, non-`__all__`-exported helper module, not a
stable public API), not because this shape is expected to move imminently.
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
    """Copy voice-assistant expose flags from source to role.

    Mirrors switch_as_x's own `copy_expose_settings` (`switch_as_x/entity.py`,
    verified against the real installed API — see this module's docstring):
    for every assistant with an explicit `should_expose` recorded for the
    source, apply the same value to the role and un-expose the source itself
    (an entity meant to be accessed only through its role should not also be
    independently exposed to a voice assistant).

    Returns True if migration ran, False if the expose-settings helper could
    not be imported on this HA version — callers treat False as "hide still
    applied, expose migration skipped", not an error.
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

    settings = exposed_entities.async_get_entity_settings(hass, from_entity_id)
    for assistant, assistant_settings in settings.items():
        should_expose = assistant_settings.get("should_expose")
        if should_expose is None:
            continue
        exposed_entities.async_expose_entity(hass, assistant, to_entity_id, should_expose)
        exposed_entities.async_expose_entity(hass, assistant, from_entity_id, False)
    return True
