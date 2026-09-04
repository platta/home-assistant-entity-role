"""Config and options flow for Entity Role — the community (UI) path (design §7).

Built on the classic config_entries.ConfigFlow / OptionsFlow base classes
with explicit voluptuous schemas, rather than `SchemaConfigFlowHandler` /
`options_flow_reloads=True`. PLAT-128 carry-forward item 1.

**Revision history on this decision, both against real evidence, reaching
the same conclusion for different (and progressively more specific)
reasons:**

*First pass* concluded `options_flow_reloads` "doesn't exist", based on a
pip-installed `homeassistant==2025.1.4` package — this sandbox's package
index does not resolve anything newer (see hide.py's module docstring).
That specific finding was **wrong**: `DECISION — ChatGPT` (PLAT-128,
2026-09-02T16:07 ET) correctly called it out, quoting `options_flow_reloads:
bool = False` from a genuinely current `home-assistant/core` `dev` checkout.

*This revision* re-verified directly against a real, current
`home-assistant/core` clone (`git clone --branch dev`, HEAD
`f01e29709bc209e54c011affd1f73fdf7a158756`, dated 2026-09-02 — this
sandbox's frozen pip index has no version of the package itself that new,
but `git clone` reaches the real repository directly, unconstrained by that
index) rather than the stale local package. Confirmed:

- `SchemaConfigFlowHandler.options_flow_reloads` is real, and when `True`
  selects `SchemaOptionsFlowHandlerWithReload` automatically —
  `schema_config_entry_flow.py` lines 308-343.
- `switch_as_x` and `group` (the design's own cited precedents) both use
  `SchemaConfigFlowHandler` today, confirmed by reading their real, current
  `config_flow.py` files directly, not assumed from the design's citation.
- `SchemaConfigFlowHandler.async_create_entry` always stores the whole
  flow's accumulated state under `entry.options` (`data={}` — line 421-422);
  `group/__init__.py::async_setup_entry` reads its role_domain equivalent
  from `entry.options["group_type"]` for exactly this reason (verified:
  `group/__init__.py` line 167). Relocating `CONF_ROLE_DOMAIN` from
  `entry.data` to `entry.options` would be required to adopt this framework
  here, but is a safe, precedented, mechanical change (group does exactly
  this) — not by itself a reason to retain the manual flow, unlike the
  impression the first pass may have given.
- Contract seeding (`_seed_contract`, a value derived from live source
  state, not itself a user-entered field) can be injected into the
  accumulated options from `SchemaFlowFormStep.validate_user_input`'s
  return value — `SchemaCommonFlowHandler._async_form_step` merges whatever
  dict `validate_user_input` returns via a plain `values.update(user_input)`
  (line ~192-195), with no restriction to schema-declared keys. This is a
  legitimate, if less obvious, use of the documented contract, not a hack.

**The one genuine, still-standing structural blocker, found by reading the
framework source line-by-line rather than assuming a fix once the two
points above turned out to be tractable:** `SchemaFlowFormStep.next_step`,
when a callable, has the signature
`Callable[[dict[str, Any]], Coroutine[Any, Any, str | None]]` and is invoked
as `await form_step.next_step(self._options)` — the *accumulated options
dict only*, with no access to `hass` or the flow handler
(`schema_config_entry_flow.py` lines 68-78, 226-231). The options flow's
"Replace hardware" step must decide whether to route to a downgrade
confirmation step based on the **live capability state of the newly
selected candidate source** (`helpers.compare_contract_to_source`, which
calls `hass.states.get(...)`) — a decision `next_step` cannot make with the
information it is given. Neither `switch_as_x` nor `group` (nor anything
found while reading `schema_config_entry_flow.py`'s own consumers) has a
next-step decision that depends on live hass state rather than only the
options accumulated so far, so there is no demonstrated real precedent for
this need. The two available workarounds — stashing the decision as an
extra key in the shared options dict during `validate_user_input` and
popping it back out inside `next_step` before it can leak into the
persisted entry, or monkey-patching `async_get_options_flow` after class
definition to substitute a hand-written options flow for the auto-generated
schema-based one (`SchemaConfigFlowHandler.__init_subclass__` overwrites
any `async_get_options_flow` defined directly in a subclass body, so this
cannot be done cleanly through inheritance either) — are both mechanically
real but neither is demonstrated anywhere in real core usage, and both are
templates for the *outward-facing config/options surface a normal user
touches on every single hardware swap* — a worse place to carry
unprecedented technique than most.

**Decision: retain the manual `ConfigFlow`/`OptionsFlow` base classes for
both flows.** Not because the framework doesn't exist or wasn't checked —
it does, and was, against the real source, twice — but because unifying the
creation and options flows under one authoring style (this integration
always has, and design §6.1/§10.3 treat behavioral consistency as a
first-class constraint) means the options flow's genuine, hass-state-
dependent branching requirement is the binding constraint on *both* flows,
not just itself: `SchemaConfigFlowHandler` cannot cleanly host a manually-
authored options flow alongside its own schema-based config flow, so
"migrate config, keep options manual" is not a clean middle path either.
Revisit if `next_step` (or an equivalent) ever gains handler/hass access, or
if a future pass is willing to accept one of the two workarounds above with
its tradeoffs made explicit — not "for its own sake".
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_DEVICE_CLASS,
    CONF_HIDE_SOURCE,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DEFAULT_HIDE_SOURCE,
    DOMAIN,
    DOMAIN_BINARY_SENSOR,
    DOMAIN_LIGHT,
    DOMAIN_SWITCH,
    SUPPORTED_DOMAINS,
)
from .helpers import (
    SourceValidationError,
    async_seed_binary_sensor_contract,
    async_seed_light_contract,
    async_seed_switch_contract,
    async_validate_source,
    compare_contract_to_source,
    lost_capabilities,
)
from .hide import async_unhide_source


class EntityRoleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Creation flow: pick domain, name + source, preview contract, confirm."""

    VERSION = 1

    def __init__(self) -> None:
        self._role_domain: str | None = None
        self._name: str | None = None
        self._source_entity_id: str | None = None
        self._contract: dict[str, Any] = {}
        self._device_class: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._role_domain = user_input[CONF_ROLE_DOMAIN]
            return await self.async_step_source()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ROLE_DOMAIN): vol.In(SUPPORTED_DOMAINS)}
            ),
        )

    async def async_step_source(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input["name"]
            # A blank/whitespace-only name is rejected here the same way the
            # declarative/YAML path rejects it (PLAT-150's `_non_blank_string`,
            # yaml_config.py): `name` is the role's durable human-facing
            # identity, distinct from both `role_id` and `source`, and this
            # UI path was the one PLAT-150 explicitly left unfixed (PLAT-155).
            # Field-scoped (not "base") so it renders under the Name field
            # specifically, independent of any source-validation error below.
            if not name.strip():
                errors["name"] = "name_blank"

            resolved: str | None = None
            try:
                resolved = async_validate_source(
                    self.hass, self._role_domain, user_input[CONF_SOURCE]
                )
            except SourceValidationError as err:
                errors["base"] = str(err)

            if not errors:
                self._name = name
                self._source_entity_id = resolved
                self._device_class = user_input.get(CONF_DEVICE_CLASS)
                self._contract = self._seed_contract(resolved)
                return await self.async_step_confirm()

        schema: dict[Any, Any] = {
            vol.Required("name"): str,
            vol.Required(CONF_SOURCE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=self._role_domain)
            ),
        }
        if self._role_domain in (DOMAIN_SWITCH, DOMAIN_BINARY_SENSOR):
            schema[vol.Optional(CONF_DEVICE_CLASS)] = str
        return self.async_show_form(
            step_id="source", data_schema=vol.Schema(schema), errors=errors
        )

    def _seed_contract(self, source_entity_id: str) -> dict[str, Any]:
        if self._role_domain == DOMAIN_LIGHT:
            return async_seed_light_contract(self.hass, source_entity_id)
        if self._role_domain == DOMAIN_SWITCH:
            return async_seed_switch_contract(self.hass, source_entity_id, self._device_class)
        return async_seed_binary_sensor_contract(self.hass, source_entity_id, self._device_class)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            hide_source = user_input.get(CONF_HIDE_SOURCE, DEFAULT_HIDE_SOURCE)
            # Hiding the source and migrating its expose settings onto the
            # role happens once the role entity actually exists (PLAT-128
            # carry-forward item 3 — see RoleEntity._apply_hide_source_policy,
            # entity.py): at this point in the flow the entry, and therefore
            # the role's own entity_id, does not exist yet.
            return self.async_create_entry(
                title=self._name,
                data={CONF_ROLE_DOMAIN: self._role_domain},
                options={
                    CONF_SOURCE: self._source_entity_id,
                    CONF_CAPABILITY_CONTRACT: self._contract,
                    CONF_DEVICE_CLASS: self._device_class,
                    CONF_HIDE_SOURCE: hide_source,
                },
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Optional(CONF_HIDE_SOURCE, default=DEFAULT_HIDE_SOURCE): bool}
            ),
            description_placeholders={
                "source": self._source_entity_id or "",
                "contract": ", ".join(
                    f"{k}={v}" for k, v in self._contract.items() if v
                )
                or "none",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "EntityRoleOptionsFlow":
        return EntityRoleOptionsFlow()


class EntityRoleOptionsFlow(config_entries.OptionsFlow):
    """Options flow: the headline "Replace hardware" operation (design §7).

    Does not accept/store `config_entry` itself: current HA (per this
    spike's own CI evidence) makes `OptionsFlow.config_entry` a read-only
    property populated by the framework — assigning it in `__init__`, the
    pattern countless older custom integrations still use, now raises
    AttributeError. `self.config_entry` is used throughout below and simply
    relies on that framework-provided property.
    """

    def __init__(self) -> None:
        self._candidate_entity_id: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_replace_hardware()

    async def async_step_replace_hardware(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        role_domain = self.config_entry.data[CONF_ROLE_DOMAIN]
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                resolved = async_validate_source(
                    self.hass, role_domain, user_input[CONF_SOURCE]
                )
            except SourceValidationError as err:
                errors["base"] = str(err)
            else:
                self._candidate_entity_id = resolved
                contract = self.config_entry.options.get(CONF_CAPABILITY_CONTRACT, {})
                classification = compare_contract_to_source(
                    role_domain, contract, self.hass, resolved
                )
                if classification == "downgrade":
                    return await self.async_step_confirm_downgrade()
                return self._apply_rebind(resolved, contract)

        return self.async_show_form(
            step_id="replace_hardware",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=role_domain)
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "current_source": self.config_entry.options.get(CONF_SOURCE, "unbound"),
            },
        )

    async def async_step_confirm_downgrade(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        role_domain = self.config_entry.data[CONF_ROLE_DOMAIN]
        contract = self.config_entry.options.get(CONF_CAPABILITY_CONTRACT, {})
        lost = lost_capabilities(contract, self.hass, self._candidate_entity_id)

        if user_input is not None:
            if not user_input.get("confirm"):
                return await self.async_step_replace_hardware()
            new_contract = dict(contract)
            if role_domain == DOMAIN_LIGHT:
                new_contract["supported_color_modes"] = sorted(
                    set(contract.get("supported_color_modes") or []) - set(lost)
                )
            return self._apply_rebind(self._candidate_entity_id, new_contract)

        return self.async_show_form(
            step_id="confirm_downgrade",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            description_placeholders={"lost_capabilities": ", ".join(lost) or "none"},
        )

    def _apply_rebind(
        self, new_source_entity_id: str, new_contract: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        # Unhiding the *old* source must happen here, before the
        # options-change reload below overwrites CONF_SOURCE: it is the last
        # point at which the previous binding is still known. Hiding the
        # *new* source and migrating its expose settings onto the role,
        # however, happens once the reload has torn down and reconstructed
        # the role entity with its real entity_id
        # (RoleEntity._apply_hide_source_policy, entity.py) — PLAT-128
        # carry-forward item 3.
        old_source = self.config_entry.options.get(CONF_SOURCE)
        hide_source = self.config_entry.options.get(CONF_HIDE_SOURCE, DEFAULT_HIDE_SOURCE)

        if hide_source and old_source and old_source != new_source_entity_id:
            async_unhide_source(self.hass, old_source)

        return self.async_create_entry(
            title="",
            data={
                **self.config_entry.options,
                CONF_SOURCE: new_source_entity_id,
                CONF_CAPABILITY_CONTRACT: new_contract,
            },
        )
