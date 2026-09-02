# PLAT-128 — Productionize Entity Role: results

**Date:** 2026-09-02
**Author:** Sonnet (dispatched producer session)
**Status:** Final.
**Authority:** accepted design `PLAT-125-hardware-role-abstraction-design.md` (Plattsoft `gitops`
repository, merge commit `af668725e9c632b12ba9c7dfc7c4e83df631250c`); accepted spike
`docs/PLAT-126-spike-results.md` (PLAT-126, merged PR #1, merge commit
`50e899a6e7e812b3518382748ad88998aff15c23`). Section references below (§N) are to the design
unless stated otherwise.

## 0. What changed since the spike, and how it was verified

The PLAT-126 spike was implemented and reviewed under a permission policy that denied outbound
package installation, `WebFetch`/`WebSearch`, and `gh api` — every §4 carry-forward item that
needed "verify against current HA APIs" was therefore left as an honest but unverified guess or
an explicitly deferred gap. This session's environment allows local package installation
(`python3 -m pip`, routed through a project-local `.venv`), which unblocked direct inspection of
a real, installed `homeassistant` package and a real local `pytest` run — the single biggest
difference from the spike's evidence base.

**A caveat this document does not gloss over:** the package index this sandbox's `pip` resolves
against is itself frozen well behind the real PyPI/GitHub state — an unpinned
`pip install homeassistant` resolved no newer than a `2025.1.4` release (confirmed by directly
attempting `homeassistant==2026.9.0`, which does not exist in this index's listing, capped at
`2025.1.4`), months to years behind the design's own dev-branch citations (`ecae90e6ad3`,
2026.10.0.dev0) and behind this repository's own CI, which resolves genuinely current releases
from the real internet. Every finding below sourced from this local install is therefore treated
as **"verified as of a real Jan-2025-era stable release, not proof of today's exact shape"** —
strong, concrete, evidence-based grounding that the spike had none of at all, but explicitly not
equivalent to the design's own dev-branch verification. Where CI (which does resolve current
releases) disagrees with a claim below, CI is authoritative — see the README's own note to the
same effect.

## 0.1. Revision round (`DECISION — ChatGPT`, 2026-09-02T16:07 ET): a real gap in how §0 was addressed

Independent review correctly found that items 1 and 2's "retain" decisions in the original pass
were partly grounded in a **false** premise: that `SchemaConfigFlowHandler.options_flow_reloads`
and `homeassistant/helpers/helper_integration.py` "don't exist". That was true only of this
sandbox's frozen local package (`homeassistant==2025.1.4`, §0 above) — not of genuinely current
`home-assistant/core`. §0's own caveat ("treat CI as authoritative over this stale local
package") was written to cover exactly this kind of risk, but the first pass still reasoned from
the stale package's *absence* of these two symbols as if it were current fact, rather than
recognizing "not present in a frozen 2025.1-era snapshot" as inconclusive on its own.

**The fix applied in this revision, not tried in the first pass:** `git clone --branch dev
https://github.com/home-assistant/core.git`, which reaches the real repository directly and is
**not** constrained by the frozen pip index — confirmed by the clone's own HEAD commit,
`f01e29709bc209e54c011affd1f73fdf7a158756`, dated 2026-09-02 (today), a plausible ~2.5 years
newer than what the frozen pip index could resolve. Every claim in the revised items 1 and 2
below is sourced from reading files at that exact commit directly, not from the local pip
package used for §§2-3 below (which remain sourced from the local package and are unaffected by
this correction — the local package is current enough for the modules those items depend on,
`homeassistant.components.homeassistant.exposed_entities` and `homeassistant.components.repairs`,
which are long-stable and did not change shape between the two).

Both items reached the **same disposition** (retain) as the first pass, but for different,
now-accurate reasons — see the table below and the module docstrings in `config_flow.py` and
`entity.py` for the full, line-cited reasoning. This is not a case of the correction being
immaterial: the *previous* reasoning was factually wrong and had to be replaced, not merely
supplemented, even though the practical outcome happened to be unchanged.

## 1. Carry-forward items (design §4 / PLAT-128 items 1–7): resolution

| # | Item | Resolution | Evidence |
|---|---|---|---|
| 1 | Config-flow base class: adopt `SchemaConfigFlowHandler`/`options_flow_reloads`, or retain the manual flow with a documented reason | **Retained — revised, now verified against real current `dev` source, not a stale local package** | See §0.1: the first pass's "doesn't exist" finding was wrong (stale local package); re-verified against a genuine `home-assistant/core` `dev` git clone. `options_flow_reloads` is real. Retained anyway, for a different, more specific reason: `SchemaFlowFormStep.next_step`'s callable signature has no `hass` access, and the options flow's downgrade-confirmation branch needs the candidate source's *live* state — a genuine, source-verified framework gap, not a version-verification gap. Full reasoning in `config_flow.py`'s module docstring. |
| 2 | Source rename/removal tracking: align with `helper_integration.async_handle_source_entity_changes` where appropriate | **Retained — revised, now verified against real current `dev` source, not a stale local package** | See §0.1: the first pass's "doesn't exist" finding was wrong; re-verified directly, including reading `switch_as_x/__init__.py`'s real current usage of it. Retained anyway: the helper is inescapably config-entry-scoped (`helper_config_entry_id` is required), so it can never serve a YAML-owned role — adopting it only for UI-owned roles would introduce the source-conditional behavior design §10.3 calls a design smell, and would also be a concrete rename-time reload/flicker regression relative to this integration's existing zero-reload in-place relink. Full reasoning in `entity.py`'s module docstring. A genuinely separate gap surfaced during this check — device-linkage (design §4) was never implemented for either configuration source — filed as `FOLLOW-UP — Sonnet`, not fixed here. |
| 3 | Expose-settings migration: replace/validate against current supported APIs | **Fixed — real, verified API; two additional real defects found and fixed** | See §2 below. |
| 4 | Repair flow/deep-link for an unbound source | **Implemented** | `repairs.py::UnboundSourceFixFlow`, modeled directly on a real in-tree fix flow that reconfigures a config entry from a repair (`homeassistant/components/workday/repairs.py`). Reuses `helpers.py`'s validation/classification functions so the options flow and the repair fix flow cannot silently diverge. `ISSUE_UNBOUND` is now `is_fixable=True` for a UI-owned role (entry_id present); a YAML-owned role's issue stays informational (`is_fixable=False`) since there is no config/options flow to deep-link into. Tests: `tests/test_repairs.py` (4 tests: full-match rebind through the fix flow, downgrade-confirmation branch, issue clearing, YAML fallback to `ConfirmRepairFlow`). |
| 5 | Dedicated UI-vs-YAML ownership isolation/collision regression coverage | **Added** | `tests/test_ownership_isolation.py` (4 tests): a UI-owned role survives a YAML reconcile to empty and to an unrelated record set; removing a UI-owned entry does not affect a YAML-owned role; the two sources' identity namespaces (config entry ID vs. author-declared `role_id`) are independently verified, not merely asserted "by construction". |
| 6 | Preserve the corrected YAML last-known-good semantics | **Preserved, untouched** | `tests/test_yaml_reconcile.py::test_existing_role_becoming_invalid_preserves_last_known_good` still passes unmodified; no code in `yaml_config.py`'s reconcile-declared-vs-removed logic was touched this pass. |
| 7 | Keep public documentation conservative about HomeKit | **Preserved** | README's HomeKit claim already carried the "not validated" caveat from the spike's own revision round; restated, not weakened, in this pass's status banner. |

## 2. Item 3 in detail: expose-settings migration, and two real defects it uncovered

The spike's `hide.py::async_migrate_expose_settings` guessed an object-returning
`exposed_entities.async_get(hass)` shape that does not exist on any installed HA version checked
in this pass. Reading `homeassistant/components/homeassistant/exposed_entities.py` directly
found the real API: module-level functions taking `hass` explicitly —
`async_get_entity_settings(hass, entity_id)` and `async_expose_entity(hass, assistant,
entity_id, should_expose)` — matching the shape `switch_as_x/entity.py::copy_expose_settings`
already uses as its own precedent. `hide.py` was rewritten against the real API.

Fixing the API shape surfaced two further, independent, real defects — found by reading the
call sites, not by guessing, and confirmed with a negative control (temporarily reintroducing
each bug against the new regression tests, confirming they turn red, then restoring the fix):

1. **The UI creation and rebind flows passed the role's display *name* as the migration
   target, not its entity_id** — a string that can never resolve to a real entity, so migration
   silently no-op'd for every UI-created role from the day this code was written (masked by the
   spike's broad `except Exception: return False`, and by `test_creation_flow_happy_path`'s own
   weak final assertion, `hass.states.async_entity_ids("light") != []`, which the *source*
   entity alone satisfies regardless of whether the role itself was ever added — also
   strengthened this pass). Root cause: the role's entity_id does not exist yet at config-flow
   time (the entry, and therefore the entity, is not created until the flow finishes). Fixed by
   moving hide/migrate entirely into `RoleEntity` (`_apply_hide_source_policy`, called from
   `async_added_to_hass` for every initial bind and from `async_rebind` for every subsequent
   one, using `self.entity_id` — always real once the entity exists), removing the calls from
   `config_flow.py` entirely rather than working around the ordering problem there.
2. **YAML-declared roles never hid their source at all**, despite `hide_source` (default `true`)
   being parsed into every record and documented in the README as a supported YAML key —
   `yaml_config.py`'s reconcile never called into `hide.py` in any form. Fixed by threading
   `hide_source` from the YAML record into `RoleEntity` the same way the UI path already does,
   and by making `async_reconcile_yaml_roles` trigger a rebind (not just on source/contract
   change) when a record's `hide_source` value itself changes.

A third, unrelated defect surfaced while fixing this: `entity.py` imported `EventStateChangedData`
from `homeassistant.core`, which does not exist there in the installed version (it lives in
`homeassistant.helpers.event`) — this broke *every* entity add in this repository's own test
suite silently (HA's `entity_platform` logs a caught "Error adding entity" rather than failing
the run), which is why the spike's CI evidence (44/44) could not have caught it: CI's pinned
`homeassistant` package apparently exports (or re-exports) it from `homeassistant.core` too, or
the spike's tests happened not to exercise the exact platform-setup path that imports it eagerly.
Fixed as a one-line import-path correction; the local `pytest` run (impossible in the spike's own
sandbox — see §0) is what caught it in the first place.

New/strengthened tests for this item: `tests/test_hide_expose.py` (6 new tests: the corrected
unit-level migration helper; end-to-end UI creation hides + migrates via the *real* entity_id;
`hide_source: false` skips both; YAML default-hides; YAML `hide_source: false` opt-out), plus the
strengthened assertion in `tests/test_config_flow.py::test_creation_flow_happy_path`.

## 2.1 Item 4 addendum: a real hassfest-only defect, caught by CI where local inspection could not

This repository's own CI (`Hassfest`) is not reproducible in this sandbox — hassfest ships as a
Docker image (`ghcr.io/home-assistant/hassfest`), not part of the `homeassistant` PyPI package —
so the first PR push relied entirely on reading a real in-tree precedent's `strings.json`
correctly by eye, and got one exclusion rule wrong: hassfest's translation schema treats a
top-level `description` and a `fix_flow` as mutually exclusive within one `issues.<key>` entry
("two or more values in the same group of exclusion 'fixable'"). The first `repairs.py` pass put
both under `issues.role_unbound`. Confirmed directly against `workday/repairs.py`'s real,
in-tree `strings.json` (already read for item 4's implementation, re-examined once the CI failure
pointed at it): its fixable issue entries (`bad_country`, `bad_province`) carry only `title` +
`fix_flow`, never a sibling `description`.

Fixed by splitting into two translation keys sharing the same runtime placeholders
(`const.py::ISSUE_UNBOUND` / `ISSUE_UNBOUND_FIXABLE`), selected in
`entity.py::_handle_source_unbound` by whether the role is UI-owned (fixable) or YAML-owned (not)
— the same condition that already governs `is_fixable` itself. Regression-tested directly
(`tests/test_repairs.py`: both keys' `issue.translation_key`, not just `is_fixable`, are now
asserted) since this is exactly the kind of defect that stays invisible to `pytest` (translation
JSON shape is a hassfest-only check, never loaded/validated by the test suite itself).

## 3. Test suite

53 tests before this pass's additions → **58 passing** locally (`.venv/bin/python -m pytest -q`,
Python 3.12, `homeassistant==2025.1.4` per §0's caveat) after: 6 new in `test_hide_expose.py`,
1 strengthened in `test_config_flow.py`, 6 new in `test_repairs.py` (including the two
translation-key regression tests from §2.1), 4 new in `test_ownership_isolation.py`. See the PR
for the authoritative CI result against genuinely current HA `stable` and `dev`.

## 4. Not done in this pass, and why

- **Live validation** (real HA instance, live rebind, HomeKit continuity, hide/unhide on real
  registries) — the ticket makes this conditional ("where the environment and authorization
  allow"). This session has no credentials or established path to the production
  `ha.plattsoft.net` instance, and connecting unreviewed-until-merged code to a production
  smart-home deployment is a materially different, higher-stakes action than writing code in
  this repository (the same framing the spike's own §5 used) — not attempted without the
  owner's explicit, separate authorization.
- **HACS readiness** — `hassfest` and the test suite are green; `HACS validation` still fails
  only on repository-publication metadata (description, topics) that a `git push`-scoped
  executor cannot set. This session does have authenticated `gh` access in this environment
  (`gh auth status`/`gh repo view` succeeded) but `gh repo edit` — the actual write — was denied
  by this session's own tool permission policy. The exact attempted command:
  ```
  gh repo edit platta/home-assistant-entity-role \
    --description "Home Assistant custom integration: a stable logical entity for a hardware role that survives replacing the underlying device." \
    --add-topic home-assistant --add-topic hacs-integration --add-topic custom-integration --add-topic home-automation
  ```
  Per the ticket's own instruction ("if repository settings... cannot be changed by the
  executor, escalate rather than weakening the claim"), this is recorded here and in the
  completion report rather than silently claimed non-blocking the way PLAT-126 adjudicated it —
  PLAT-128 is explicitly the HACS-readiness milestone that adjudication deferred this to.
- **Manifest version** bumped `0.1.0` → `0.2.0` to reflect this pass; a `1.0.0` claim is
  deliberately withheld pending the two items above.
