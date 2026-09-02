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

> **Status: implementation spike.** This repository currently implements the bounded proof-of-
> concept scope defined by the accepted design (see [Design](#design) below), not a
> production-complete v1. HA entity identity/rebind/capability-contract/declarative-path behavior
> above is implemented and test-verified in CI; live HomeKit/Apple Home continuity across a rebind
> is **not validated in this environment** (no Apple Home client was reachable) and remains a
> design expectation, not a proven one. See `docs/PLAT-126-spike-results.md` for the full,
> gate-by-gate account of what has and has not been validated.

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

## Supported domains (v1 spike)

`light`, `switch` (including the `outlet` device class), `binary_sensor` (e.g. `door`/`window`).

## Design

This integration implements the bounded spike scope of the accepted design
`PLAT-125-hardware-role-abstraction-design.md` (Plattsoft `gitops` repository,
merge commit `af668725e9c632b12ba9c7dfc7c4e83df631250c`). That document is the authoritative
architecture reference; see `docs/PLAT-126-spike-results.md` in this repository for how this
implementation maps onto its spike gates.

## Installation

Via [HACS](https://hacs.xyz/) as a custom repository (`platta/home-assistant-entity-role`,
category "Integration"), or manually by copying `custom_components/entity_role/` into your Home
Assistant `config/custom_components/` directory and restarting.

## Development

```console
pip install -r requirements_test.txt
pytest
```

CI runs `hassfest`, HACS validation, and the test suite against both the current stable and the
`dev` (RC) branch of Home Assistant core.

## License

MIT — see `LICENSE`.
