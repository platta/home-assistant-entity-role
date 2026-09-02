"""Config and options flow for Entity Role — the community (UI) path (design §7).

Built on the classic config_entries.ConfigFlow / OptionsFlow base classes
with explicit voluptuous schemas, rather than `SchemaConfigFlowHandler` /
`options_flow_reloads=True`. PLAT-128 carry-forward item 1 ("verify current
HA helper/config-flow conventions and decide whether to adopt
SchemaConfigFlowHandler... or retain the manual flow with a documented
reason"): the spike could not verify this at all (no outbound repository
access). This pass installed a real, current homeassistant package (see
hide.py's module docstring for the environment-constraints note) and read
`homeassistant/helpers/schema_config_entry_flow.py` plus its two real
consumers, `switch_as_x/config_flow.py` and `group/config_flow.py`, directly
— so this is now a verified decision, not an unresolved gap:

- `SchemaConfigFlowHandler` is confirmed real, current, and actively used by
  two of the exact core precedents this design already cites (switch_as_x,
  group) — not a hypothetical convenience.
- No `options_flow_reloads` attribute or keyword exists anywhere in that
  module in the installed version; `switch_as_x/__init__.py` reloads on
  options change the same way this integration already does — an explicit
  `entry.add_update_listener(...)` (`config_entry_update_listener` there,
  `_async_update_listener` here) — so that specific design citation appears
  to describe a newer/dev-only refinement this sandbox's package index
  cannot resolve (see the README's environment-constraints note), not a
  currently-shipping difference in how reload-on-options-change works.
- `SchemaFlowFormStep` supports the dynamic pieces this integration's flows
  need (an async `next_step` callable for the downgrade-confirmation branch,
  `validate_user_input` for raising a `SchemaFlowError`, async
  `suggested_values`) — adopting it here is a real option, not blocked by a
  shape mismatch.

Decision: retain the manual `ConfigFlow`/`OptionsFlow` base classes. Both are
current, fully-supported, non-deprecated core APIs (confirmed directly, not
assumed) — this is not the "could not verify, played it safe" position the
spike was in. The manual flow already correctly implements every behavior
`SchemaConfigFlowHandler` would provide here (contract seeding from live
state, downgrade-confirmation branching, hide/expose side effects,
reload-on-options-change) and is covered by this repository's own test
suite; rewriting a multi-step, dynamically-branching, side-effecting flow —
the most consumer-visible surface in this integration — for a boilerplate
reduction with no behavioral difference was judged unwarranted risk for a
production pass, not a limitation to accept silently. Revisit if a future
pass finds a concrete reason `SchemaConfigFlowHandler` specifically is
required (e.g. a core policy change), rather than migrating for its own
sake.
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
            try:
                resolved = async_validate_source(
                    self.hass, self._role_domain, user_input[CONF_SOURCE]
                )
            except SourceValidationError as err:
                errors["base"] = str(err)
            else:
                self._name = user_input["name"]
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
