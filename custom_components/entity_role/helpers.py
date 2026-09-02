"""Shared helpers: source resolution, bind-time validation, contract seeding.

Source entities are referenced by entity-registry UUID wherever the config
flow persists them, resolved fresh via entity_registry.async_validate_entity_id
at every setup/rebind — the switch_as_x pattern verified in the PLAT-125
design (§2.1/§4): that helper accepts either an entity_id or a registry UUID
and always returns the entity's *current* entity_id, so a UUID-pinned
reference survives a rename (including one that happened while HA was down)
while a plain entity_id reference breaks at the next reload — the documented
trade-off in design §6.4, not a bug.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


class SourceValidationError(Exception):
    """Raised when a candidate source entity cannot be bound to a role."""


def async_resolve_source_ref(hass: HomeAssistant, source_ref: str) -> str | None:
    """Resolve a persisted source reference (entity_id or registry UUID).

    Returns the source's *current* entity_id, or None if the reference no
    longer resolves — either because the registry entry was removed, or
    (for a plain-entity_id reference) because it was renamed, per the
    module docstring. Callers treat None as "unbound".

    `er.async_validate_entity_id`'s raised-exception type has moved across
    HA versions (vol.Invalid vs. HomeAssistantError); catching broadly here
    keeps this call site independent of that rather than guessing.

    Verified against CI evidence (this spike's own first CI run):
    `er.async_validate_entity_id` does *not* raise for a syntactically
    well-formed entity_id that simply has no registry entry — it passes the
    string through unchanged. An explicit registry-existence check below is
    therefore required to actually detect "not found" / "removed", not
    optional defensive coding.
    """
    registry = er.async_get(hass)
    try:
        entity_id = er.async_validate_entity_id(registry, source_ref)
    except Exception:  # noqa: BLE001 - see docstring; any failure means "unresolved"
        return None
    if registry.async_get(entity_id) is None:
        return None
    return entity_id


def async_validate_source(
    hass: HomeAssistant, role_domain: str, source_ref: str, *, exclude_role_id: str | None = None
) -> str:
    """Validate a candidate source for a new/rebound role.

    Raises SourceValidationError with a stable, user-facing reason code in
    args[0] for: unresolvable source, domain mismatch, or a direct
    role-on-role binding (design §10.1 R3 — indirect cycles are handled at
    forward time by RoleEntity.async_forward_command's re-entrancy guard,
    since they cannot be detected statically from registry data alone).
    """
    entity_id = async_resolve_source_ref(hass, source_ref)
    if entity_id is None:
        raise SourceValidationError("source_not_found")

    source_domain = entity_id.split(".", 1)[0]
    if source_domain != role_domain:
        raise SourceValidationError("domain_mismatch")

    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is not None and entry.platform == DOMAIN:
        raise SourceValidationError("role_on_role_rejected")

    return entity_id


def async_seed_light_contract(hass: HomeAssistant, source_entity_id: str) -> dict[str, Any]:
    state = hass.states.get(source_entity_id)
    if state is None:
        return {"supported_color_modes": [], "supported_features": 0}
    return {
        "supported_color_modes": list(state.attributes.get("supported_color_modes") or []),
        "supported_features": int(state.attributes.get("supported_features") or 0),
    }


def async_seed_switch_contract(
    hass: HomeAssistant, source_entity_id: str, device_class: str | None
) -> dict[str, Any]:
    return {"device_class": device_class}


def async_seed_binary_sensor_contract(
    hass: HomeAssistant, source_entity_id: str, device_class: str | None
) -> dict[str, Any]:
    return {"device_class": device_class}


def compare_contract_to_source(
    role_domain: str, contract: dict[str, Any], hass: HomeAssistant, source_entity_id: str
) -> str:
    """Classify a candidate rebind as "match", "downgrade", or "upgrade".

    Only meaningful for light (the one v1 domain with a set-valued
    capability); switch/binary_sensor contracts are role-declared device
    classes with no hardware-capability comparison (design §5, §9.2, §9.3).
    """
    if role_domain != "light":
        return "match"

    state = hass.states.get(source_entity_id)
    source_modes = set((state.attributes.get("supported_color_modes") if state else None) or [])
    contract_modes = set(contract.get("supported_color_modes") or [])

    if not contract_modes:
        return "match"
    if source_modes >= contract_modes:
        return "match" if source_modes == contract_modes else "upgrade"
    return "downgrade"


def lost_capabilities(contract: dict[str, Any], hass: HomeAssistant, source_entity_id: str) -> list[str]:
    """Contract capabilities the candidate source cannot deliver (for the
    downgrade confirmation shown in both the UI options flow and, as a
    warning repair issue, the YAML path)."""
    state = hass.states.get(source_entity_id)
    source_modes = set((state.attributes.get("supported_color_modes") if state else None) or [])
    contract_modes = set(contract.get("supported_color_modes") or [])
    return sorted(contract_modes - source_modes)
