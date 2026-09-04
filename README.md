# Entity Role

A [Home Assistant](https://www.home-assistant.io/) custom integration that gives you a
**stable logical entity** for a hardware role — `light.kitchen_counter`, say — that keeps its
identity (entity ID and unique ID) for life, no matter what physical device is currently behind
it.

Replace a dead bulb, swap a Zigbee plug for a Matter one, or move a contact sensor to different
hardware, and every automation, scene, and dashboard card that references the role keeps working
— untouched. HomeKit accessory identity is *designed* to derive from that same stable unique ID
(Home Assistant's own HomeKit bridge keys accessories on it), so a role is expected to carry its
Apple Home accessory across a hardware swap the same way — but that specific claim has **not**
been validated against a real Apple Home client yet; see the status note below.

> **Status: v1, community-quality.** PLAT-126's implementation spike has been productionized
> (PLAT-128): all §4 carry-forward items — config-flow convention verification, source
> rename/removal tracking, expose-settings migration against the real current HA API, an
> HA-native repair-issue deep-link for an unbound role, and dedicated UI-vs-YAML ownership
> regression coverage — are resolved or explicitly, documentedly retained. HA entity
> identity/rebind/capability-contract/declarative-path behavior is implemented and test-verified
> in CI. Two things remain **not validated**, honestly: live HomeKit/Apple Home continuity across
> a rebind (no Apple Home client was reachable from this environment) stays a design expectation,
> not a proven one; and this repository is not yet claiming HACS-readiness — see
> [HACS status](#hacs-status) below. See `docs/PLAT-126-spike-results.md` for the spike's
> gate-by-gate account and `docs/PLAT-128-production-results.md` for this pass's.

## What it does

- **Create a role** for a light, switch/outlet, or contact (binary) sensor through Home
  Assistant's normal Settings → Devices & Services → Helpers UI — pick the domain, name it, and
  point it at the hardware entity it should currently proxy.
- **Replace hardware** at any time through the role's own Configure → Options flow. The role's
  identity never changes; consumers see a brief state refresh, nothing more.
- The role advertises **`capability contract ∩ current hardware`** — you declare what the role
  promises (e.g. "this light supports color"), and the role only ever exposes what both the
  contract *and* the currently-bound hardware actually support. A downgrade (swapping in
  simpler hardware) asks for confirmation and narrows the advertised capabilities; an upgrade
  stays inert until you widen the contract yourself.
- If the bound hardware is removed, **the role survives** — it goes unavailable and raises a
  repair notification, rather than disappearing. Bind replacement hardware whenever you're
  ready.
- Everything above works with **zero Git/YAML/automation knowledge required**. A normal
  Home-Assistant user never has to see anything but the standard Helpers UI.

## Advanced: declarative (YAML) configuration

For deployments that manage Home Assistant configuration as code, roles can instead be declared
under a domain-key `entity_role:` block and reloaded without restarting HA via the
`entity_role.reload` service — the same dual-path pattern Home Assistant's own `template`
integration uses. A role is owned by exactly one source (UI *or* YAML, never both); nothing about
the declarative path is visible anywhere in the UI-only experience above.

Each declared role has three distinct identities, and every field below except
`capability_contract`/`device_class`/`hide_source` is **required**:

- `role_id` — the durable *machine* identity (the slug behind the entity's `unique_id`/`entity_id`).
- `name` — the durable *human-facing* identity (what you and Home Assistant's UI actually call the
  role). Required, and must not be blank/whitespace-only — it is never derived from `role_id` or
  from the bound hardware, so replacing the hardware behind a role never changes what it's called.
- `source` — the *replaceable physical implementation* currently bound to the role (an `entity_id`,
  or, recommended for Git-managed deployments, an entity-registry UUID — see the design).

```yaml
entity_role:
  - role_id: kitchen_counter
    role_domain: light
    source: light.nanoleaf_a19_kitchen   # entity_id, or (recommended for Git-managed
                                          # deployments) an entity-registry UUID — see the design
    name: Kitchen Counter
    capability_contract:
      supported_color_modes: [hs, color_temp]
      supported_features: 0
    hide_source: true
```

A record missing `name`, or whose `name` is blank/whitespace-only, fails validation with a repair
issue (Settings → Repairs) rather than falling back to `role_id` or being silently accepted — see
`yaml_config.py`'s module docstring for the exact compatibility behavior for a role that already
existed before `name` became required.

An empty declaration — `entity_role: []`, or an `!include` pointing at a file that is empty
or contains only comments — is valid and means zero YAML-owned roles; it will not fail HA
startup. This is the expected state for a fresh GitOps install or a recovery/bootstrap
checkout before any household roles have been declared yet.

## Recovering an unbound role

If a role's bound hardware is removed from Home Assistant, the role survives unavailable and
raises a repair issue (Settings → Repairs). Selecting **Fix** on that issue opens the same
"pick a replacement" step as the role's own Configure → Options flow, directly from the repair
— no need to separately find the role first.

## Supported domains (v1)

`light`, `switch` (including the `outlet` device class), `binary_sensor` (e.g. `door`/`window`).

## Design

This integration implements the accepted design
`PLAT-125-hardware-role-abstraction-design.md` (Plattsoft `gitops` repository,
merge commit `af668725e9c632b12ba9c7dfc7c4e83df631250c`). That document is the authoritative
architecture reference. `docs/PLAT-126-spike-results.md` records the initial bounded spike's
gate-by-gate results; `docs/PLAT-128-production-results.md` records this production pass —
including two verified decisions to retain the spike's manual config-flow base classes and
custom source-tracking listener rather than adopt newer core helpers cited in the design, with
the evidence behind each.

## HACS status

Not yet claimed HACS-ready. `hassfest` and the test suite (HA stable + dev) are green; **HACS
validation** currently fails only on repository-publication metadata this integration's own code
cannot set — the repository has no description or topics yet (`hacsjson`, `integration_manifest`,
and `brands` are believed to be a metadata-gated cascade from that, per `docs/PLAT-126-spike-
results.md` §0's negative-result test, not independent content defects). Setting a description
and topics (`home-assistant`, `hacs-integration`, `custom-integration`, `home-automation`) via
repository Settings or `gh repo edit` — outside what a repository-scoped `git push` can do — would
resolve this; see `docs/PLAT-128-production-results.md` for the exact attempted command and why
it was not run unattended.

## Installation

Via [HACS](https://hacs.xyz/) as a custom repository (`platta/home-assistant-entity-role`,
category "Integration"), or manually by copying `custom_components/entity_role/` into your Home
Assistant `config/custom_components/` directory and restarting.

## Development

```console
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest
```

CI runs `hassfest`, HACS validation, and the test suite against both the current stable and the
`dev` (RC) branch of Home Assistant core — always resolving genuinely current package releases.
A local sandboxed dev environment's package index may be frozen well behind the real PyPI/GitHub
state (observed directly during PLAT-128: a `pip install homeassistant` with no version pin
resolved no newer than a `2025.1.4` release from one such index, versus this repository's own CI
correctly resolving the real current stable/dev releases) — treat CI, not a local install's
version, as the authority on "current supported HA APIs" if the two ever disagree.

## License

MIT — see `LICENSE`.
