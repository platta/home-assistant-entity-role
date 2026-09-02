"""Declarative (YAML) configuration source for Entity Role (design §6.1, §6.3).

Domain-key YAML only (`entity_role:` — see ADR-0007 compliance in design
§6.5): the parsed role list is split by role_domain and dispatched to each
platform via homeassistant.helpers.discovery.async_load_platform, so no
platform-key YAML (`light: {platform: entity_role}`) is ever required or
accepted. Reload re-reads the file via
homeassistant.helpers.reload.async_integration_yaml_config (the same helper
template/__init__.py::_reload_config uses, verified in design §2.3/§10.1 R7)
and reconciles running roles to it *in place* rather than unloading and
recreating them — see async_reconcile_yaml_roles docstring for the R7
failure-mode contract this depends on.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_DEVICE_CLASS,
    CONF_HIDE_SOURCE,
    CONF_ROLE_DOMAIN,
    CONF_ROLE_ID,
    CONF_SOURCE,
    DATA_YAML_ROLES,
    DEFAULT_HIDE_SOURCE,
    DOMAIN,
    ISSUE_YAML_RECORD_INVALID,
    SUPPORTED_DOMAINS,
)
from .helpers import SourceValidationError, async_validate_source

_LOGGER = logging.getLogger(__name__)

ROLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ROLE_ID): cv.slug,
        vol.Required(CONF_ROLE_DOMAIN): vol.In(SUPPORTED_DOMAINS),
        vol.Required(CONF_SOURCE): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional(CONF_CAPABILITY_CONTRACT, default=dict): dict,
        vol.Optional(CONF_DEVICE_CLASS): cv.string,
        vol.Optional(CONF_HIDE_SOURCE, default=DEFAULT_HIDE_SOURCE): cv.boolean,
    }
)


class _RecordError(Exception):
    def __init__(self, role_id: str, reason: str) -> None:
        super().__init__(reason)
        self.role_id = role_id
        self.reason = reason


def _validate_records(
    hass: HomeAssistant, raw_records: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[_RecordError]]:
    """Schema-parse + bind-validate every record.

    A record that fails validation is reported but does not reject the rest
    of the file (design §10.1 R7's per-record degrade) — the file as a whole
    is only ever "invalid" upstream, at YAML-syntax/top-level-schema level,
    handled by async_integration_yaml_config before this function is called
    at all (see async_reconcile_yaml_roles docstring).
    """
    valid: dict[str, dict[str, Any]] = {}
    errors: list[_RecordError] = []
    seen_role_ids: set[str] = set()

    for raw in raw_records:
        try:
            record = dict(ROLE_SCHEMA(raw))
        except vol.Invalid as err:
            role_id = raw.get(CONF_ROLE_ID, "<unknown>") if isinstance(raw, dict) else "<unknown>"
            errors.append(_RecordError(role_id, f"schema_invalid: {err}"))
            continue

        role_id = record[CONF_ROLE_ID]
        if role_id in seen_role_ids:
            errors.append(_RecordError(role_id, "duplicate_role_id"))
            continue
        seen_role_ids.add(role_id)

        try:
            resolved = async_validate_source(
                hass, record[CONF_ROLE_DOMAIN], record[CONF_SOURCE]
            )
        except SourceValidationError as err:
            errors.append(_RecordError(role_id, str(err)))
            continue

        record["_resolved_source"] = resolved
        valid[role_id] = record

    return valid, errors


async def async_setup_yaml(hass: HomeAssistant, config: ConfigType) -> None:
    hass.data.setdefault(DOMAIN, {}).setdefault(DATA_YAML_ROLES, {})
    if DOMAIN not in config:
        return
    await async_reconcile_yaml_roles(hass, config)


async def async_reconcile_yaml_roles(hass: HomeAssistant, config: ConfigType | None) -> None:
    """Reconcile running YAML-owned roles to the given parsed configuration.

    Callers (async_setup_yaml, the reload service handler) are responsible
    for the file-level failure mode: when
    `helpers.reload.async_integration_yaml_config` returns None for an
    unparseable file or a top-level-schema-invalid one, this function must
    not be called at all — the caller leaves the last-known-good running
    roles untouched, which is `template`'s own verified behavior for the
    same failure (design §10.1 R7). This function only ever sees a
    syntactically valid `config`, and handles *record*-level invalidity
    itself: a bad record is flagged via repair issue and every other role
    reconciles normally.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    current: dict[str, dict[str, Any]] = domain_data.setdefault(DATA_YAML_ROLES, {})
    roles: dict[str, Any] = domain_data.setdefault("roles", {})

    raw_records = list((config or {}).get(DOMAIN, []))
    valid, errors = _validate_records(hass, raw_records)

    for error in errors:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_YAML_RECORD_INVALID}_{error.role_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_YAML_RECORD_INVALID,
            translation_placeholders={"role_id": error.role_id, "reason": error.reason},
        )
        _LOGGER.warning("entity_role YAML record %s invalid: %s", error.role_id, error.reason)

    # Clear stale issues for records that are valid again.
    for role_id in valid:
        ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_YAML_RECORD_INVALID}_{role_id}")

    # Removed: previously YAML-owned, no longer declared in a valid record.
    for role_id in set(current) - set(valid):
        entity = roles.get(role_id)
        if entity is not None:
            await entity.async_remove(force_remove=True)
        current.pop(role_id, None)

    # New: declared now, not previously running — batched per role_domain
    # since async_load_platform dispatches one platform setup call per
    # (component, discovery) pair.
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for role_id, record in valid.items():
        if role_id in current:
            continue
        by_domain.setdefault(record[CONF_ROLE_DOMAIN], []).append(record)

    for role_domain, records in by_domain.items():
        await discovery.async_load_platform(
            hass, role_domain, DOMAIN, {"roles": records}, {DOMAIN: raw_records}
        )

    # Existing: rebind in place rather than unload/recreate, so identity
    # (unique_id -> HomeKit aid) and consumer references are undisturbed
    # across a reload — the "candidate refinement" flagged in design §10.2
    # #4, adopted here as the implemented behavior (see spike results).
    for role_id, record in valid.items():
        if role_id not in current:
            continue
        entity = roles.get(role_id)
        if entity is None:
            continue
        if (
            entity.source_entity_id != record["_resolved_source"]
            or entity.contract != record[CONF_CAPABILITY_CONTRACT]
        ):
            await entity.async_rebind(record[CONF_SOURCE], record[CONF_CAPABILITY_CONTRACT])

    domain_data[DATA_YAML_ROLES] = valid
