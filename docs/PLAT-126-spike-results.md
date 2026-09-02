# PLAT-126 — Entity Role implementation spike: results

**Date:** 2026-09-02
**Author:** Sonnet (dispatched producer session)
**Status:** Final, revised. A first pass was adjudicated on functional evidence
(`DECISION — ChatGPT`, PLAT-126, 2026-09-02T11:31 ET: `HACS validation` non-blocking — see §0),
then sent back for revision (`DECISION — ChatGPT`, 2026-09-02T12:14 ET): a real last-known-good
defect in YAML reconciliation (item 10/gate (d)) and README wording that overstated live HomeKit
continuity as proven. Both are now fixed and CI-verified: `pytest` is green — 44/44 on both HA
`stable` and `dev` (43 plus the new regression test
`test_existing_role_becoming_invalid_preserves_last_known_good`) — on PR HEAD
`1cb02a1b22298ca07745d06a167ac653e418c393`, along with `hassfest`. `HACS validation` remains
adjudicated non-blocking per the first decision, and this repository is still explicitly **not**
claimed HACS-ready.
**Authority:** accepted design `PLAT-125-hardware-role-abstraction-design.md` (Plattsoft `gitops`
repository, merge commit `af668725e9c632b12ba9c7dfc7c4e83df631250c`). Section references below
(§N) are to that document unless stated otherwise.

## 0. How to read this document

Every gate below is one of:

- **PASS** — implemented and verified by an automated test in this repository, cited by path.
- **PARTIAL** — implemented, but with a documented gap, simplification, or unverified dependency.
- **NOT VALIDATED IN THIS ENVIRONMENT** — genuinely out of reach of this sandbox (no live Apple
  Home client, no authorization to modify the production `gitops`/cluster deployment) — explicitly
  unproven, not claimed.
- **PENDING CI** — implemented and covered by a test, but this document was drafted before this
  repository's GitHub Actions run against the real `homeassistant`/`pytest-homeassistant-custom-
  component` packages had produced a result; see the PR for the current run.

This spike could not install the `homeassistant` package or run `pytest` inside the dispatching
session's own sandbox (outbound `pip install` is denied under this session's permission policy).
All test-suite evidence below is therefore CI evidence (GitHub Actions, `.github/workflows/
validate.yml`), not something independently re-run inside the chat session — recorded here as an
observed constraint, not glossed over.

That constraint was not merely theoretical: the PR's first four CI runs (33645135079,
33646016670, 33646589394, 33647054906) surfaced a chain of real bugs this session's own review
had not caught — a wrong import module, an entity-registry helper that resolves a nonexistent
entity_id instead of rejecting it, `OptionsFlow.config_entry` now being a read-only
framework-populated property, a missing `services.yaml`, a light capability attribute that must
be a real `LightEntityFeature` flag rather than a plain `int`, HA `dev`'s independent Python
floor, a stale repair issue on UI rebind, and two test-authoring bugs (an ambiguous
domain-wide entity lookup, and a test double that replaced the real service handler it meant to
observe). Each was root-caused from the actual failure/traceback before being fixed — none were
guessed-and-retried. The fifth run (33647054906) is green on `pytest (HA stable)`, `pytest (HA
dev)` (43/43 each), and `Hassfest`.

`HACS validation` is the one remaining red check, and is not a code defect: it reports the
repository has no description and no topics (both true — this is a brand-new repository) plus
three further checks (`hacsjson`, `integration_manifest`, `brands`) whose messages ("expected a
dictionary. Got None") read as content-validation failures but are not. This session tested that
directly: `hacs.json`'s content was changed (dropping the optional `homeassistant` minimum-version
key) between runs 33647054906 and 33647933316, and the same three checks failed identically
before and after — ruling out `hacs.json` content as the cause. The remaining, uneliminated
hypothesis is that these three checks are gated behind the repository having valid
description/topics in the first place (a cascade, not four independent defects), but this could
not be confirmed further without outbound access to the HACS validator's source (`WebFetch`,
`WebSearch`, `curl`, and `gh api` are all denied under this session's permission policy — a
dispatched research subagent hit the identical wall). Setting the repository's description and
topics is a `gh repo edit` call this session's permission policy does not allow; it was requested
of the user in-session and remained outstanding when this session's initial pass at this document
was written.

**Adjudication (`DECISION — ChatGPT`, PLAT-126, 2026-09-02T11:31 ET):** this failure was
adjudicated non-blocking for the spike's CI-readiness gate, on constraints quoted verbatim below
because they bound what this document is allowed to claim:

- "The functional/architecture validation that this spike exists to prove is green: Hassfest
  passes, HA stable pytest passes (43/43), and HA dev pytest passes (43/43)."
- "The remaining HACS failure is repository-publication metadata (description / topics) that is
  outside the implementation branch and cannot be changed under the current executor permission
  boundary."
- "PLAT-126 is an implementation spike, not a HACS publication/readiness ticket. The ticket
  requires a packaging/maintenance skeleton, not successful community-directory publication."
- "Do not claim the repository is HACS-ready."
- "If, after repository metadata is eventually supplied, HACS validation exposes genuine
  integration-content failures beyond metadata/cascade behavior, those must be fixed before any
  future HACS-release/readiness milestone."

**Follow-up (non-blocking, tracked here per that decision rather than filed as a separate Jira
issue by this session):** once the repository's description/topics are set, re-run HACS
validation and confirm hacsjson/integration_manifest/brands clear along with it, confirming the
cascade hypothesis above. If any of the three still fail once metadata is present, that is a
genuine content defect requiring a real fix before a HACS-release milestone — not something this
document can rule out today.

**Revision round (`DECISION — ChatGPT`, PLAT-126, 2026-09-02T12:14 ET):** review of the first
REPORT found a real correctness defect in `yaml_config.py::async_reconcile_yaml_roles`: it
computed "removed" as `set(current) - set(valid)`, which conflated two distinct cases — a role
genuinely omitted from the YAML file, and a role still declared in the file whose new record had
become invalid (bad source, schema error, …). The latter case was being deleted, violating the
last-known-good resilience behavior item 10/gate (d) exists to prove. Fixed by tracking which
role_ids are "declared" (valid or invalid) versus genuinely absent, and only removing the latter;
an invalid-but-still-declared role now keeps running on its prior binding (untouched, issue
raised) rather than being torn down, and `DATA_YAML_ROLES` preserves its last-known-good record so
a later corrected reconcile takes the in-place-rebind path rather than being treated as new. See
`tests/test_yaml_reconcile.py::test_existing_role_becoming_invalid_preserves_last_known_good` for
the regression test (the 5-step scenario the decision specified), and the README fix for the
separate HomeKit-overclaim finding in that same review round.

## 1. Summary and recommendation

**Recommendation: proceed to production implementation**, with the specific open items in §4
carried into that pass rather than re-litigated. The core architectural bet in the PLAT-125
design — one role model, two configuration sources, `contract ∩ source` capability semantics,
survive-not-delete on source loss, cycle safety — is implemented and covered by automated tests
for every mechanism that does not require a live Apple Home client or write access to the
production `gitops` deployment. Nothing encountered while implementing the spike invalidates a
PLAT-125 assumption; the deviations in §4 are implementation *choices* forced by this sandbox's
lack of live-core-source verification tooling, not evidence against the design.

## 2. Ticket scope items 1–12: results

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 1 | Stable logical role entity proxies a source, retains identity across rebind | PASS | `tests/test_light_role.py::test_rebind_preserves_identity_and_updates_contract`, `tests/test_identity.py` |
| 2 | Representative v1 domain coverage: light prioritized, switch + binary_sensor for shared architecture | PASS | `custom_components/entity_role/{light,switch,binary_sensor}.py`; `tests/test_switch_binary_sensor.py` |
| 3 | Source bindings use durable HA entity-registry identity where designed | PASS | `helpers.async_resolve_source_ref` (registry UUID or entity_id, via `entity_registry.async_validate_entity_id`); `tests/test_source_validation.py::test_resolve_by_registry_uuid` |
| 4 | Rebind via standard HA config/options flows works without breaking the logical entity | PASS | `custom_components/entity_role/config_flow.py::EntityRoleOptionsFlow`; `tests/test_config_flow.py` |
| 5 | Capability contract: `contract ∩ source`, including downgrade | PASS | `entity.py::contract_intersect_iterable/_bitmask`; `tests/test_light_role.py::test_contract_intersection_narrows_downgraded_hardware`; `tests/test_config_flow.py::test_options_flow_replace_hardware_downgrade_requires_confirmation` |
| 6 | Source unavailable/removed leaves role intact and recoverable | PASS | `entity.py::_handle_source_unbound`; `tests/test_availability_unbound.py` |
| 7 | Direct role→role recursion rejected; indirect/re-entrant cycle safety | PASS | `helpers.async_validate_source` (static reject); `entity.py::async_forward_command` (runtime guard); `tests/test_source_validation.py::test_validate_rejects_direct_role_on_role`, `tests/test_cycle_guard.py` |
| 8 | Repeated hide/unhide + expose-setting migration, hiding optional/default-on | PARTIAL | Hide/unhide: PASS (`tests/test_hide_expose.py`). Expose-setting migration: best-effort, unverified against live core — see §4 |
| 9 | HomeKit continuity validated live | NOT VALIDATED IN THIS ENVIRONMENT | No Apple Home client or live paired HomeKit bridge is reachable from this sandbox; connecting this spike to the production HA instance was not attempted without separate authorization — see §5 |
| 10 | Declarative/YAML path: reload w/o restart, stable identity, malformed-file/record handling, last-known-good, revert convergence, in-place vs. recreate | PASS (in-place adopted; last-known-good fix CI-verified) | `custom_components/entity_role/yaml_config.py`; `tests/test_yaml_reconcile.py`, `tests/test_reload_service.py`, `tests/test_identity.py`. A real defect here (an existing role whose new record was present-but-invalid was deleted instead of kept on its last-known-good binding, conflating "invalid" with "removed") was found on review (`DECISION — ChatGPT`, PLAT-126, 2026-09-02T12:14 ET), fixed, and confirmed by `test_existing_role_becoming_invalid_preserves_last_known_good` passing in CI (44/44, PR HEAD `1cb02a1`) |
| 11 | Deployment-side Git→Flux→config→reload chain feasibility | PARTIAL | The integration-side half (the `entity_role.reload` admin service a PLAT-119-style reconciler would call) is implemented and tested. The live Flux/ConfigMap/reconciler chain in the `gitops` deployment was **not** exercised — that is deployment configuration outside this integration's repository (design §6.3, §11: "the spike writes no integration code into `gitops`"), and stands up/modifies the production cluster, which this ticket did not authorize |
| 12 | Packaging/maintenance skeleton: manifest versioning, CI against supported HA APIs | PASS (adjudicated) | `manifest.json` (`version: 0.1.0`), `hacs.json`, `.github/workflows/validate.yml` (hassfest + HACS validation + pytest against HA `stable` and `dev`). Hassfest and pytest (stable + dev, 44/44 each as of the revision round) are green. `HACS validation` fails on repository-publication metadata outside this branch, adjudicated non-blocking for this spike — see §0. The repository is **not** claimed HACS-ready |

## 3. Design §11 spike gates (a)–(g)

| Gate | Verdict | Evidence |
|---|---|---|
| (a) automation/scene/dashboard references survive a live rebind | PASS at the identity level | entity_id/unique_id proven unchanged across rebind (`test_rebind_preserves_identity_and_updates_contract`); this spike does not stand up a real automation/scene to observe end-to-end, since identity stability is the concrete property those consumers depend on and it is what is tested |
| (b) HomeKit identity/characteristics on a real Apple Home client | NOT VALIDATED IN THIS ENVIRONMENT | see item 9 above and §5 |
| (c) restart with missing source → unavailable+repair → clean recovery | PASS | `tests/test_availability_unbound.py` |
| (d) YAML: reload w/o restart, restart convergence, invalid-file/-record handling, revert round trip | PASS (last-known-good fix CI-verified), ConfigMap-mount question **not addressed** | `tests/test_yaml_reconcile.py`, `tests/test_reload_service.py`, `tests/test_identity.py`; see item 10's note on the last-known-good fix. The ConfigMap-mount-vs-reconciler-written-file question (design §10.2 #27) is deployment-side (item 11) and out of this repository's scope |
| (e) UX non-regression: UI-only install exposes zero GitOps concepts | PASS by construction | The UI config/options flows (`config_flow.py`) never reference YAML, `role_id`, or any GitOps concept; `strings.json`/`translations/en.json` contain no such terms. Not independently reviewed by a second party — recorded as implemented-per-design, not externally audited |
| (f) unit tests: rename/removal/rebind/downgrade × both sources, ownership/collision rules, hide/expose shuttling, curated attributes | PASS (light/switch/binary_sensor curated attributes); ownership/collision rule test gap — see §4 | `tests/` (all files); duplicate-`role_id` collision is tested (`test_yaml_reconcile.py::test_duplicate_role_id_only_first_record_accepted`); the UI-vs-YAML cross-ownership rule (§6.1: "UI-owned roles are ignored by YAML reconciliation entirely") has no dedicated test — see §4 |
| (g) cycle safety: direct rejected, indirect re-entrancy guard | PASS | `tests/test_source_validation.py::test_validate_rejects_direct_role_on_role`, `tests/test_cycle_guard.py` |

## 4. Design deviations and open items (carry into a production pass)

None of the following invalidate a PLAT-125 assumption; each is a concrete, bounded gap this
spike could not close without capabilities unavailable in this sandbox (outbound access to fetch
live HA core source at a specific commit, as the design's own research phase had).

1. **Config/options flow base class.** The design cites `SchemaConfigFlowHandler` with
   `options_flow_reloads=True` (verified in the design against `switch_as_x`/`group` at a
   specific core commit). This spike uses the classic `config_entries.ConfigFlow`/`OptionsFlow`
   base classes with manual steps and an explicit `add_update_listener` reload
   (`__init__.py::_async_update_listener`) instead, because this session had no way to fetch and
   verify `SchemaConfigFlowHandler`'s current declarative-schema shape against live core source.
   Functionally equivalent for every behavior this spike tests; a production pass should verify
   whether adopting `SchemaConfigFlowHandler` is still warranted for parity with core helpers.
2. **Live rename/removal tracking.** The design delegates this to
   `homeassistant.helpers.helper_integration.async_handle_source_entity_changes` (verified in the
   design for `switch_as_x`, a config-entry-only helper). This spike instead implements its own
   registry listener (`entity.py::_handle_registry_event`, built on
   `entity_registry.async_track_entity_registry_updated_event` and
   `entity_registry.async_validate_entity_id`) so the same code path serves both the UI and YAML
   sources uniformly. Covered by `tests/test_availability_unbound.py`, but a production pass
   should verify whether the core helper is adoptable for the config-entry path specifically.
3. **Expose-settings migration** (`hide.py::async_migrate_expose_settings`) is best-effort against
   `homeassistant.components.homeassistant.exposed_entities`, an internal helper this session
   could not verify the current shape of; it degrades to a logged warning (hide itself still
   succeeds) rather than failing if that shape has moved. CI (§0) will show whether the import
   succeeds against the pinned HA versions; treat that as informative, not conclusive proof the
   full migration semantics are correct.
4. **Repair-issue deep-link into the rebind options step** (design §10.2 #26) is not implemented;
   the design itself marks this UNVERIFIED. The repair issue is created/cleared correctly
   (tested); today it does not offer an inline fix flow.
5. **UI-vs-YAML cross-ownership rule** (§6.1: a UI-created role is invisible to YAML
   reconciliation, and vice versa) is implemented by construction — the two sources never share
   a role_id/entry_id namespace and `async_reconcile_yaml_roles` only ever touches roles present
   in `DATA_YAML_ROLES` — but has no dedicated regression test in this spike.
6. **HACS validation is red, non-blocking by adjudication.** Hassfest and pytest are green — see
   §0. `HACS validation` fails on repository-publication metadata (`description`/`topics`) this
   session cannot set, and was adjudicated non-blocking for this spike's completion
   (`DECISION — ChatGPT`, PLAT-126). Setting that metadata and confirming
   `hacsjson`/`integration_manifest`/`brands` clear along with it is the concrete follow-up before
   any future HACS-release/readiness milestone — not before this spike's own completion.

## 5. Item 9 / gate (b): why HomeKit continuity was not validated live

The accepted design (§9.1) already verifies from core source that HomeKit accessory identity
derives from `unique_id` (stable across rebind) and that `homekit/accessories.py`'s
`_reload_on_change_attrs` mechanism reacts to capability changes in place. Actually exercising
this against a real Apple Home client requires a live, HomeKit-bridged Home Assistant instance
paired to an Apple device. This spike had no such environment available, and connecting an
unreviewed spike integration to the user's production Home Assistant instance
(`ha.plattsoft.net`, per PLAT-116/117/118/122) was not attempted without separate, explicit
authorization — installing experimental code into a production smart-home deployment is a
materially different action from writing code in this repository. This gate remains explicitly
unproven, per the design's own framing ("as far as the available environment permits").

## 6. Assumptions invalidated by the spike

None identified. Every mechanism the design flagged as **Resolved** in its risk register (§10.2)
implemented cleanly against the APIs the design already verified; every mechanism flagged
**Spike** in that register is addressed in §§2–3 above (as PASS, PARTIAL, or explicitly not
validated in this environment) rather than surfacing a new architectural problem.
