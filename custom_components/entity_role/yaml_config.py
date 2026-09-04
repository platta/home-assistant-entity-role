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

**`name` required (PLAT-150) — compatibility for a pre-existing record that
omits it:** `ROLE_SCHEMA` now rejects a record with a missing or
blank/whitespace-only `name` as `schema_invalid`, exactly like any other
per-record schema violation — it flows through the same R7 degrade path
(`_validate_records` -> `_RecordError` -> `ISSUE_YAML_RECORD_INVALID` repair
issue) rather than a bespoke migration mechanism. The practical effect
differs by when the record is (re-)evaluated:

* **Live reload** (`entity_role.reload`, no HA restart) of a role that was
  already running: the record becomes "declared but invalid"
  (`invalid_but_declared` below) and, per R7's last-known-good contract, its
  already-constructed entity is left completely untouched — same bound
  source, same previously-set display name — while the repair issue nudges
  the author to add `name:`. No identity/name change happens silently.
* **A cold HA restart** after upgrading past this record's `DATA_YAML_ROLES`
  reset to empty every reconcile, a name-less record is invalid from the
  first evaluation and is simply never constructed — no "declared but
  invalid" carry-forward applies, since there is no prior running instance
  in the same session to preserve. The role goes fully unavailable (not
  "silently renamed"; the pre-existing HA entity-registry entry, if any,
  keeps whatever name was last recorded in the registry) with the same
  repair issue surfaced, until `name:` is added and the file reloads/HA
  restarts again.

Not evidence of a released/versioned config format needing a version-gated
migration: `manifest.json` is pre-1.0 (`0.3.0`), there are no git tags/HACS
releases, and `YAML_SCHEMA_VERSION` (const.py) has never been wired to any
actual migration logic — this repository has no external users to migrate
yet. The R7 degrade-with-repair-issue path above is this integration's
existing, already-tested idiom for exactly this class of "record became
invalid under new code" case, reused here rather than inventing a new one.
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
    CONF_NAME,
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


def _non_blank_string(value: Any) -> str:
    """`cv.string` plus a blank/whitespace-only rejection (PLAT-150).

    `name` is the role's durable human-facing identity (design intent per
    PLAT-150: `role_id` is machine identity, `source` is the replaceable
    physical implementation, `name` is what a person sees) — a value that is
    present but empty or all-whitespace is exactly as useless as an absent
    one, so it must fail validation the same way rather than silently
    producing a blank Home Assistant display name.
    """
    value = cv.string(value)
    if not value.strip():
        raise vol.Invalid("name must not be blank")
    return value


ROLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ROLE_ID): cv.slug,
        vol.Required(CONF_ROLE_DOMAIN): vol.In(SUPPORTED_DOMAINS),
        vol.Required(CONF_SOURCE): cv.string,
        # Required (PLAT-150): a declarative role's human-facing display name
        # must be explicit — it must never fall back to `role_id` (a
        # machine-identity slug) as it silently did before. See this
        # module's docstring reference and the platform `from_yaml_record`
        # classmethods (light.py/switch.py/binary_sensor.py), which now read
        # `record[CONF_NAME]` directly instead of defaulting it.
        vol.Required(CONF_NAME): _non_blank_string,
        vol.Optional(CONF_CAPABILITY_CONTRACT, default=dict): dict,
        vol.Optional(CONF_DEVICE_CLASS): cv.string,
        vol.Optional(CONF_HIDE_SOURCE, default=DEFAULT_HIDE_SOURCE): cv.boolean,
    }
)


def _ensure_role_records(value: Any) -> list[Any]:
    """Normalize the raw `entity_role:` YAML value to a list of records.

    Delegates to `cv.ensure_list` for the general case, but first treats a
    blank/absent value as "zero declared roles" rather than letting
    `cv.ensure_list` wrap it into a single-item list. This matters because
    a valid empty declaration — `entity_role: []` directly, or an
    `!include` resolving to an empty file — must mean zero roles, not one
    empty role record:

    * `entity_role:` with no value parses to `None`.
    * `homeassistant.util.yaml.loader._include_yaml` itself substitutes an
      empty *dict* (`NodeDictClass()`) whenever the included file's content
      parses to `None` — e.g. a fresh GitOps-owned file that is empty or
      contains only comments, the bootstrap/recovery state this integration
      must support (see PLAT-144).

    Without this, `cv.ensure_list({})` wraps that empty dict into `[{}]`,
    and per-record validation against `ROLE_SCHEMA` then fails with
    `required key not provided` for every required field, exactly as if a
    single, entirely blank role record had been declared. A genuine
    single-record shorthand (a non-empty dict) still wraps normally, and an
    explicit list — empty or not — passes through unchanged.
    """
    if value is None or value == {}:
        return []
    return cv.ensure_list(value)


ROLE_LIST_SCHEMA = vol.All(_ensure_role_records, [ROLE_SCHEMA])


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

    # A role_id still present in the file — valid or not — is "declared".
    # Only a role_id genuinely absent from the file is "removed" (design
    # §10.1 R7's last-known-good contract, DECISION — ChatGPT PLAT-126
    # 2026-09-02T12:14 ET: a role that is *still declared but now invalid*
    # must keep its prior running binding/state, not be deleted — that
    # distinction is exactly what declared_role_ids draws. Errors with no
    # recoverable role_id ("<unknown>" — e.g. the role_id field itself is
    # missing/malformed) can never match a running role and are excluded.
    declared_role_ids = set(valid) | {e.role_id for e in errors if e.role_id != "<unknown>"}
    invalid_but_declared = declared_role_ids - set(valid)

    # Removed: previously YAML-owned, no longer declared in the file at all.
    for role_id in set(current) - declared_role_ids:
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
        record_hide_source = record[CONF_HIDE_SOURCE]
        if (
            entity.source_entity_id != record["_resolved_source"]
            or entity.contract != record[CONF_CAPABILITY_CONTRACT]
            or entity.hide_source != record_hide_source
        ):
            await entity.async_rebind(
                record[CONF_SOURCE], record[CONF_CAPABILITY_CONTRACT], record_hide_source
            )

    # Track last-known-good for roles still declared but currently invalid,
    # instead of dropping them: their entity was never touched above, so
    # their tracked record must keep pointing at what it is actually still
    # bound to. A later reconcile with a corrected record then finds
    # role_id already in `current` and takes the in-place rebind path
    # above, rather than being treated as a brand-new role.
    new_tracked: dict[str, dict[str, Any]] = dict(valid)
    for role_id in invalid_but_declared:
        if role_id in current:
            new_tracked[role_id] = current[role_id]
    domain_data[DATA_YAML_ROLES] = new_tracked
