"""Repair-issue integration for Entity Role.

PLAT-128 carry-forward item 4 ("implement the repair flow/deep-link or
otherwise provide a polished HA-native recovery UX for an unbound/missing
source"): the spike explicitly left this UNVERIFIED/PARTIAL (design §10.2
#26) because it could not check the real `homeassistant.components.repairs`
API shape without outbound access. This pass installed a real, current
homeassistant package (see hide.py's module docstring for the same
environment note) and read that package's `repairs/models.py` and
`repairs/issue_handler.py` directly, plus a real in-tree fix flow that
reconfigures a config entry from a repair
(`homeassistant/components/workday/repairs.py::CountryFixFlow`/
`HolidayFixFlow`) as the precedent this module follows: a repairs platform
exports a module-level `async_create_fix_flow(hass, issue_id, data)`,
discovered by `homeassistant.helpers.integration_platform` because this
module is named `repairs.py` at the integration's top level — the existing
placement was already correct, only the (previously entirely stubbed-out)
implementation was missing.

Only `ISSUE_UNBOUND` (entity.py) is ever created with `is_fixable=True`, and
only when the unbound role is UI-owned (`entry_id` present in the issue's
`data` — see `RoleEntity._handle_source_unbound`): a YAML-owned role's fix is
"edit the file and reload", which is not a UI-flow-shaped action, so that
case stays `is_fixable=False` exactly as before. `ISSUE_YAML_RECORD_INVALID`
(yaml_config.py) remains not fixable for the same reason — its record lives
in a Git-managed file this integration does not write to (design §6.3: "the
integration itself never talks to Git").

`UnboundSourceFixFlow` below deliberately does not subclass
`EntityRoleOptionsFlow` (config_flow.py): `OptionsFlow.config_entry` is a
framework-populated property tied specifically to the config-entries options
flow manager, not the repairs flow manager, and forcing the two together
would rely on undocumented cooperation between two different FlowHandler
subclasses. Instead — matching workday's own `CountryFixFlow`/
`HolidayFixFlow`, which take the same approach rather than subclassing
`WorkdayOptionsFlow` — it reuses the shared, source-of-truth validation and
classification helpers (`helpers.py`) so the two entry points into a rebind
(options flow, repair fix flow) cannot silently diverge in what counts as a
valid replacement or a capability downgrade, while each owns its own thin
flow-step scaffolding.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import CONF_CAPABILITY_CONTRACT, CONF_ROLE_DOMAIN, CONF_SOURCE, DOMAIN_LIGHT
from .helpers import (
    SourceValidationError,
    async_validate_source,
    compare_contract_to_source,
    lost_capabilities,
)


class UnboundSourceFixFlow(RepairsFlow):
    """Deep-link straight into "pick a replacement" for a UI-owned role
    whose source was removed — the flow the `source_entity_removed`
    docstring anticipates (design §7 "Unbound recovery"), reached directly
    from the repair issue instead of requiring the extra "open Configure"
    click the spike's own README documented as the gap here.
    """

    def __init__(self, entry: ConfigEntry, role_domain: str) -> None:
        self._entry = entry
        self._role_domain = role_domain
        self._candidate_entity_id: str | None = None
        super().__init__()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_replace_hardware()

    async def async_step_replace_hardware(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                resolved = async_validate_source(
                    self.hass, self._role_domain, user_input[CONF_SOURCE]
                )
            except SourceValidationError as err:
                errors["base"] = str(err)
            else:
                self._candidate_entity_id = resolved
                contract = self._entry.options.get(CONF_CAPABILITY_CONTRACT, {})
                classification = compare_contract_to_source(
                    self._role_domain, contract, self.hass, resolved
                )
                if classification == "downgrade":
                    return await self.async_step_confirm_downgrade()
                return await self._async_apply_rebind(resolved, contract)

        return self.async_show_form(
            step_id="replace_hardware",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=self._role_domain)
                    )
                }
            ),
            errors=errors,
            description_placeholders={"title": self._entry.title},
        )

    async def async_step_confirm_downgrade(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        contract = self._entry.options.get(CONF_CAPABILITY_CONTRACT, {})
        lost = lost_capabilities(contract, self.hass, self._candidate_entity_id)

        if user_input is not None:
            if not user_input.get("confirm"):
                return await self.async_step_replace_hardware()
            new_contract = dict(contract)
            if self._role_domain == DOMAIN_LIGHT:
                new_contract["supported_color_modes"] = sorted(
                    set(contract.get("supported_color_modes") or []) - set(lost)
                )
            return await self._async_apply_rebind(self._candidate_entity_id, new_contract)

        return self.async_show_form(
            step_id="confirm_downgrade",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            description_placeholders={"lost_capabilities": ", ".join(lost) or "none"},
        )

    async def _async_apply_rebind(
        self, new_source_entity_id: str, new_contract: dict[str, Any]
    ) -> data_entry_flow.FlowResult:
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={
                **self._entry.options,
                CONF_SOURCE: new_source_entity_id,
                CONF_CAPABILITY_CONTRACT: new_contract,
            },
        )
        # async_update_entry already fires this entry's update listener
        # (__init__.py::_async_update_listener) when options actually
        # changed, which reloads it — but that firing is not guaranteed to
        # have completed by the time this flow finishes. Mirrors the
        # explicit reload in the real, verified precedent this module
        # follows (workday/repairs.py's fix flows) rather than relying on
        # that implicitly.
        await self.hass.config_entries.async_reload(self._entry.entry_id)
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Route a fixable Entity Role issue to its fix flow.

    Only ISSUE_UNBOUND issues are ever created with is_fixable=True, and
    only for a UI-owned role (entry_id present and still resolvable) — see
    this module's docstring.
    """
    if data and (entry_id := data.get("entry_id")):
        entry = hass.config_entries.async_get_entry(str(entry_id))
        if entry is not None:
            return UnboundSourceFixFlow(entry, entry.data[CONF_ROLE_DOMAIN])
    return ConfirmRepairFlow()
