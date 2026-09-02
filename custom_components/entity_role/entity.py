"""Shared base entity for Entity Role roles.

Implements the mechanisms verified against core in the PLAT-125 design
(switch_as_x / group precedent): state/attribute proxying via
async_track_state_change_event, availability mirroring, service-context
propagation, durable-identity resolution via
entity_registry.async_validate_entity_id (helpers.async_resolve_source_ref),
and — per design §10.1 R3 — a re-entrant command-forwarding guard for
indirect role→…→role cycles (direct role-on-role bindings are rejected
earlier, at bind-validation time; see helpers.async_validate_source).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import Context, Event, EventStateChangedData, State, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import (
    async_track_entity_registry_updated_event,
    async_track_state_change_event,
)

from .const import DATA_FORWARD_CHAINS, DOMAIN, ISSUE_UNBOUND
from .helpers import async_resolve_source_ref

_LOGGER = logging.getLogger(__name__)

STATE_UNAVAILABLE = "unavailable"


class RoleEntity(Entity):
    """Common behavior for every Entity Role platform entity.

    Subclasses (light/switch/binary_sensor) are thin: they translate
    domain-specific state/attributes from the source and, for controllable
    domains, forward commands through async_forward_command.
    """

    _attr_should_poll = False

    def __init__(
        self,
        role_id: str,
        role_domain: str,
        name: str,
        source_entity_id: str | None,
        contract: dict[str, Any],
        source_ref: str | None = None,
    ) -> None:
        self._role_id = role_id
        self._role_domain = role_domain
        self._attr_unique_id = role_id
        self._attr_name = name
        # `source_ref` is the persisted reference (registry UUID or plain
        # entity_id) as configured; `source_entity_id` is its resolution at
        # last (re)bind. They are re-reconciled on every registry event —
        # see _handle_registry_event.
        self._source_ref: str | None = source_ref if source_ref is not None else source_entity_id
        self._source_entity_id = source_entity_id
        self._contract = dict(contract)
        self._source_state: State | None = None
        self._remove_state_listener: Callable[[], None] | None = None
        self._remove_registry_listener: Callable[[], None] | None = None

    # -- identity / binding ---------------------------------------------------

    @property
    def role_id(self) -> str:
        """The stable logical identity of this role (unique_id)."""
        return self._role_id

    @property
    def source_entity_id(self) -> str | None:
        """The currently bound implementation entity, or None if unbound."""
        return self._source_entity_id

    @property
    def contract(self) -> dict[str, Any]:
        return dict(self._contract)

    @property
    def source_state(self) -> State | None:
        return self._source_state

    # -- HA entity lifecycle ---------------------------------------------------

    @property
    def available(self) -> bool:
        """Unavailable when unbound, or when the source is missing/unavailable.

        Design §8: this is deliberately different from switch_as_x — the role
        entity itself is never removed when its source disappears.
        """
        if self._source_entity_id is None:
            return False
        if self._source_state is None:
            return False
        return self._source_state.state != STATE_UNAVAILABLE

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        roles: dict[str, RoleEntity] = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            "roles", {}
        )
        roles[self._role_id] = self
        self._resync_source_state()
        self._subscribe_source()
        if self._source_entity_id is not None:
            # Covers both configuration sources' route back to "bound":
            # YAML rebinds this same entity instance in place (async_rebind
            # already clears the issue there too), but the UI/config-entry
            # path reloads the entry — tearing this entity down and
            # constructing a *new* instance from the updated options, which
            # never goes through async_rebind at all. Confirmed by this
            # spike's own CI: without this, a stale unbound issue survived
            # a UI rebind indefinitely.
            ir.async_delete_issue(self.hass, DOMAIN, f"{ISSUE_UNBOUND}_{self._role_id}")

    async def async_will_remove_from_hass(self) -> None:
        self._unsubscribe_source()
        roles: dict[str, RoleEntity] | None = self.hass.data.get(DOMAIN, {}).get("roles")
        if roles is not None:
            roles.pop(self._role_id, None)
        await super().async_will_remove_from_hass()

    def _resync_source_state(self) -> None:
        self._source_state = (
            self.hass.states.get(self._source_entity_id)
            if self._source_entity_id is not None
            else None
        )

    def _subscribe_source(self) -> None:
        self._unsubscribe_source()
        if self._source_entity_id is None:
            return
        self._remove_state_listener = async_track_state_change_event(
            self.hass, [self._source_entity_id], self._handle_source_event
        )
        self._remove_registry_listener = async_track_entity_registry_updated_event(
            self.hass, self._source_entity_id, self._handle_registry_event
        )

    def _unsubscribe_source(self) -> None:
        if self._remove_state_listener is not None:
            self._remove_state_listener()
            self._remove_state_listener = None
        if self._remove_registry_listener is not None:
            self._remove_registry_listener()
            self._remove_registry_listener = None

    @callback
    def _handle_source_event(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        self._source_state = new_state
        if new_state is not None:
            # Propagate the triggering context so traces/logbook stay
            # coherent through the proxy (design §8, the GroupEntity
            # precedent).
            self.async_set_context(event.context)
        if self.hass is not None:
            self.async_write_ha_state()

    @callback
    def _handle_registry_event(self, event: Event[dict[str, Any]]) -> None:
        """React to the bound source's registry entry changing.

        Re-resolves `self._source_ref` (not the current entity_id) on every
        registry update/removal — see helpers.async_resolve_source_ref for
        why this alone correctly distinguishes a UUID-pinned reference
        surviving a rename from a removal (or an entity_id-pinned reference
        breaking on rename, the documented design §6.4 caveat), without a
        dependency on the specific shape of the registry event's payload.
        """
        if self._source_ref is None:
            return
        resolved = async_resolve_source_ref(self.hass, self._source_ref)
        if resolved == self._source_entity_id:
            return  # unrelated registry change (e.g. area/name) — no-op
        if resolved is None:
            self.hass.async_create_task(self._handle_source_unbound())
        else:
            self.hass.async_create_task(self._handle_source_relinked(resolved))

    async def _handle_source_unbound(self) -> None:
        """Source removed from the registry (design §8): survive, go
        unavailable, and raise a repair issue that deep-links back into the
        replace-hardware options step."""
        _LOGGER.warning(
            "%s: bound source is no longer resolvable, role is now unbound",
            self.entity_id,
        )
        await self.async_rebind(None)
        if self.platform is not None and self.platform.config_entry is not None:
            entry_id = self.platform.config_entry.entry_id
        else:
            entry_id = None
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_UNBOUND}_{self._role_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_UNBOUND,
            translation_placeholders={
                "role_name": self.name or self._role_id,
                "entity_id": self.entity_id or self._role_id,
            },
            data={"role_id": self._role_id, "entry_id": entry_id},
        )

    async def _handle_source_relinked(self, new_entity_id: str) -> None:
        """A UUID-pinned source survived a rename or device move while this
        role was running — resubscribe to its new entity_id, identity
        unchanged."""
        _LOGGER.debug(
            "%s: bound source relinked %s -> %s",
            self.entity_id,
            self._source_entity_id,
            new_entity_id,
        )
        self._unsubscribe_source()
        self._source_entity_id = new_entity_id
        self._resync_source_state()
        self._subscribe_source()
        self.async_write_ha_state()

    # -- rebind / unbind --------------------------------------------------------

    async def async_rebind(
        self, new_source_ref: str | None, new_contract: dict[str, Any] | None = None
    ) -> None:
        """Rebind (or unbind, if new_source_ref is None) this role.

        Identity (unique_id/entity_id) never changes. Accepts the same
        reference form as configuration (registry UUID or entity_id);
        resolves it exactly as at initial bind. Called from the options
        flow (UI path) and from YAML reconciliation (declarative path) —
        both configuration sources converge on this one method, per the
        "one role model" rule in design §6.1/§10.3.
        """
        self._unsubscribe_source()
        self._source_ref = new_source_ref
        self._source_entity_id = (
            async_resolve_source_ref(self.hass, new_source_ref)
            if new_source_ref is not None
            else None
        )
        if new_contract is not None:
            self._contract = dict(new_contract)
        self._resync_source_state()
        self._subscribe_source()
        if self.hass is not None:
            ir.async_delete_issue(self.hass, DOMAIN, f"{ISSUE_UNBOUND}_{self._role_id}")
            self.async_write_ha_state()

    def async_update_contract(self, contract: dict[str, Any]) -> None:
        self._contract = dict(contract)

    # -- capability contract (design §5: advertise contract ∩ source) -----------

    def contract_intersect_iterable(self, key: str, source_value: Any) -> list[Any]:
        """Set-valued capability: advertise contract ∩ source, e.g. color modes."""
        contract_value = self._contract.get(key)
        if not contract_value or source_value is None:
            return []
        return sorted(set(contract_value) & set(source_value))

    def contract_intersect_bitmask(self, key: str, source_value: int | None) -> int:
        """Bitmask-valued capability: advertise contract & source."""
        contract_value = self._contract.get(key, 0) or 0
        if source_value is None:
            return 0
        return int(contract_value) & int(source_value)

    # -- command forwarding with cycle guard (design §10.1 R3) -------------------

    async def async_forward_command(
        self, service: str, service_data: dict[str, Any] | None = None
    ) -> None:
        """Forward a command to the bound source entity.

        Drops (with a logged error, no exception raised to the caller) rather
        than forwards when the incoming service-call context has already
        passed through this role — the re-entrancy guard for an indirect
        cycle such as role -> group -> the same role, which cannot be
        rejected statically at bind time (design §10.1 R3, spike gate g).
        Direct role-on-role bindings are rejected earlier, at bind-validation
        time (see helpers.async_validate_source).
        """
        if self._source_entity_id is None:
            _LOGGER.warning(
                "%s: cannot forward %s, role is unbound", self.entity_id, service
            )
            return

        context = self._context or Context()
        domain_data = self.hass.data.setdefault(DOMAIN, {})
        chains: dict[str, set[str]] = domain_data.setdefault(DATA_FORWARD_CHAINS, {})
        visited = chains.setdefault(context.id, set())

        if self._role_id in visited:
            _LOGGER.error(
                "%s: dropped %s.%s — command re-entered this role's own "
                "forwarding chain (cycle guard, PLAT-125 R3)",
                self.entity_id,
                self._role_domain,
                service,
            )
            return

        visited.add(self._role_id)
        try:
            await self.hass.services.async_call(
                self._role_domain,
                service,
                {"entity_id": self._source_entity_id, **(service_data or {})},
                blocking=True,
                context=context,
            )
        finally:
            visited.discard(self._role_id)
            if not visited:
                chains.pop(context.id, None)
