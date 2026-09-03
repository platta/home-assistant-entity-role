# PLAT-130 — Entity Role device linkage: results

**Date:** 2026-09-02
**Author:** Sonnet (dispatched producer session)
**Status:** Final.
**Authority:** accepted design `PLAT-125-hardware-role-abstraction-design.md` (Plattsoft `gitops`
repository, merge commit `af668725e9c632b12ba9c7dfc7c4e83df631250c`), §4 "Device linkage";
`FOLLOW-UP — Sonnet` on PLAT-128 (the gap this ticket closes); accepted PLAT-128 production
implementation, merge commit `8561e32af60fa5f320fe6b2f9377ce33ccebeaf5`.

## 1. What was implemented

Every role entity's registry `device_id` now tracks whatever HA device its currently bound
source entity belongs to — the design §4 requirement ("like `switch_as_x`, the logical entity
sets its registry `device_id` to the source's device, so it appears on the physical device's
page") — for both configuration sources, kept correct across initial bind, rebind, source
removal, and the source itself moving to a different device.

Implementation lives entirely in `entity.py::RoleEntity._sync_device_link`, called from every
path that can change what a role is bound to: `async_added_to_hass` (initial bind, both sources,
and the UI's fresh-instance-per-reload path), `async_rebind` (YAML in-place rebind and the
repair fix flow's rebind), `_handle_source_relinked` (a UUID-pinned source surviving a rename in
place), and the "unrelated registry change" branch of `_handle_registry_event` (a source device
move where the source's own entity_id does not change).

## 2. The mechanism, and why it is not `switch_as_x`'s own mechanism

The design's own §4 text cites `switch_as_x` and `async_handle_source_entity_changes` together.
This ticket's own instructions (and PLAT-128's already-accepted decision, restated here rather
than re-litigated) are explicit: do not adopt the helper wholesale, because it is inescapably
config-entry-scoped (`helper_config_entry_id` is a required parameter) and therefore cannot serve
a YAML-owned role at all — adopting it only for UI-owned roles would be exactly the
source-conditional behavior design §10.3 calls a smell.

Verified directly against a real, current `home-assistant/core` `dev` clone
(`git clone --depth 1 --branch dev`, fetched 2026-09-02 — this sandbox's frozen local `pip`
index, capped at a `2025.1.4`-era release per PLAT-128's own documented environment constraint,
was not used for this verification):

- `switch_as_x`'s own entities (`switch_as_x/entity.py::BaseEntity.__init__`) attach to a device
  by setting `self.device_entry` directly at construction, from the wrapped entity's registry
  `device_id`. This only works because `switch_as_x` entities are always added through a config
  entry.
- `homeassistant/helpers/entity_platform.py::EntityPlatform._async_add_entity` only honors
  `entity.device_info`/`entity.device_entry` when `self.config_entry` is set. For an entity added
  without one, `_check_device_attach` (lines ~839-852) silently forces `device_entry = None` and
  logs a deprecation report (`breaks_in_ha_version="2027.8.0"`) instead of attaching anything.
  Every YAML-owned role is added exactly that way, via `discovery.async_load_platform` (design
  §6.1) — so the add-time mechanism structurally cannot serve both configuration sources, full
  stop, independent of any helper-adoption question.
- `entity_registry.async_update_entity(entity_id, device_id=...)` — a plain, already-registered-
  entity registry write — has no such restriction:
  `entity_registry.py::_validate_item` only checks that the target device exists in the device
  registry (lines ~1168-1174), never that the entity has a config entry. This is also the exact
  primitive `helper_integration.async_handle_source_entity_changes` itself uses internally to
  relink on a source device move (`helper_integration.py`'s `async_registry_updated`).

The chosen mechanism therefore mirrors that one registry-write primitive — real, current, and
already core's own way of expressing "this entity is linked to that device" — behind this
integration's own unified, source-agnostic call site (`_sync_device_link`), instead of adopting
the config-entry-scoped helper that produced it. A role's registry entry starts at
`device_id=None` (RoleEntity never sets `device_entry`/`device_info`) and is promoted or demoted
only by `_sync_device_link`, through the same code path for both ownership modes — there is no
per-source branch to keep in sync by hand.

**Compatibility implication:** because this only uses the generic
`entity_registry.async_update_entity` API (long-stable, not the specific `helper_integration`
module whose own risk register entry — design §10.2 #22 — already documents observed churn),
this feature carries no additional exposure to that specific churn risk beyond what PLAT-128
already accepted for source tracking generally.

## 3. Requirements checklist

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | UI-created role linked to source device on initial bind | **Done** | `tests/test_device_linkage.py::test_ui_role_linked_to_source_device_on_initial_bind` |
| 2 | YAML-created role linked to source device on initial bind | **Done** | `test_yaml_role_linked_to_source_device_on_initial_bind` |
| 3 | Stable identity across rebind; device linkage moves to the replacement source | **Done** | `test_rebind_relinks_to_new_source_device_identity_preserved` (YAML in-place rebind) and `test_ui_rebind_relinks_to_new_source_device_identity_preserved` (UI reload-and-reconstruct rebind — a structurally different code path, see §1) |
| 4 | Source with no device yields no fabricated helper-owned device | **Done** | `test_source_without_device_role_stays_unlinked_no_fabricated_device` — also asserts the device registry contains zero devices, since this integration never calls `device_registry.async_get_or_create` |
| 5 | Source removal/unbind safely detaches linkage, role preserved | **Done** | `test_source_removed_detaches_device_link_role_preserved` |
| 6 | Source moving to another HA device updates role linkage | **Done** | `test_source_device_move_updates_role_linkage` — the source's entity_id is unchanged, only its `device_id`, exercising `_handle_registry_event`'s "unrelated" branch specifically |
| 7 | Tests cover both ownership modes and the lifecycle cases above | **Done** | `tests/test_device_linkage.py`, 7 new tests |
| 8 | No duplicate/co-owned/forked physical devices created | **Done by construction** | `_sync_device_link` only ever reads an existing device_id off the source's own registry entry or clears the role's own; no device-registry write of any kind |
| 9 | HA stable/dev tests and Hassfest remain green | **Green locally; CI is authoritative** — see §4 | Local suite: 65 passed (`'.venv/bin/python -m pytest -q'`, Python 3.12, `homeassistant==2025.1.4`); CI result for the exact delivered PR HEAD is recorded in the Jira completion report, not guessed here |
| 10 | Documentation records the chosen mechanism and compatibility implications | **Done** | This document, §2 |

## 4. Validation

- **Local test suite:** 58 → 65 passing (`tests/test_device_linkage.py` adds 7; nothing else
  touched behaviorally). `.venv/bin/python -m pytest -q`.
- **Negative control:** `_sync_device_link` was temporarily short-circuited to a no-op
  (`return` as its first statement) and the suite re-run scoped to the new file: 5 of the 6
  original assertions on stored `device_id` went red as expected; the "source has no device"
  test correctly stayed green either way (a no-op linker also leaves an already-`None` link
  alone). The fix was then restored and the full suite re-confirmed green (65 passed). This
  confirms the new tests actually exercise `_sync_device_link`, not merely alongside it.
- Per this ticket's own scope boundaries, no GitOps/Kubernetes-specific logic, no HomeKit live
  validation, and no HACS work was touched — those remain governed by PLAT-128's own
  already-recorded open items.
