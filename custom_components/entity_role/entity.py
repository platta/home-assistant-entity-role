"""Shared base entity for Entity Role roles.

Implements the mechanisms verified against core in the PLAT-125 design
(switch_as_x / group precedent): state/attribute proxying via
async_track_state_change_event, availability mirroring, service-context
propagation, durable-identity resolution via
entity_registry.async_validate_entity_id (helpers.async_resolve_source_ref),
and — per design §10.1 R3 — a re-entrant command-forwarding guard for
indirect role→…→role cycles (direct role-on-role bindings are rejected
earlier, at bind-validation time; see helpers.async_validate_source).

**Rename/removal tracking (PLAT-128 carry-forward item 2)**: `_handle_
registry_event` below is this integration's own registry listener
(`entity_registry.async_track_entity_registry_updated_event` +
`entity_registry.async_validate_entity_id`), not the design-cited
`homeassistant.helpers.helper_integration.async_handle_source_entity_changes`.

**Revision history on this decision:** a first pass claimed
`helper_integration.py` "does not exist" at all, based on a
pip-installed `homeassistant==2025.1.4` package this sandbox's package index
is frozen at (see hide.py's module docstring). `DECISION — ChatGPT`
(PLAT-128, 2026-09-02T16:07 ET) correctly rejected that: the module is real
on current `dev`, modified 2026-08-20. This revision re-verified directly
against a real, current `home-assistant/core` clone (`git clone --branch
dev`, HEAD `f01e29709bc209e54c011affd1f73fdf7a158756`, dated 2026-09-02 —
`git clone` reaches the real repository directly, unconstrained by this
sandbox's frozen pip index) — both `helper_integration.py` and
`switch_as_x/__init__.py` were read in full at that commit, not assumed.

Confirmed, precisely:

- `async_handle_source_entity_changes` is real, current, and genuinely used
  by `switch_as_x/__init__.py::async_setup_entry` today (verified: it wraps
  the whole registry-change lifecycle for that integration's config entry).
- It is **inescapably config-entry-scoped**: `helper_config_entry_id` is a
  required keyword argument, used internally both for
  `hass.config_entries.async_reload(helper_config_entry_id)` and for
  `entity_registry.entities.get_entries_for_config_entry_id(
  helper_config_entry_id)` (`helper_integration.py` lines 63-122). A
  YAML-owned role has no config entry at all — this helper has no
  applicability to that configuration source, full stop, not a matter of
  preference.
- Survive-not-delete on removal (design §8's asymmetry vs. switch_as_x) *is*
  achievable through the helper's own `source_entity_removed` callback —
  its docstring explicitly anticipates "ask the user to select a new source
  entity" as a valid use (line 42-44). The first pass's docstring understated
  this; corrected here. This is not, by itself, a reason to prefer or avoid
  the helper.
- The concrete behavioral cost of adopting it for UI-owned roles specifically
  — corrected per `DECISION — ChatGPT` (PLAT-128, 2026-09-02T16:29 ET): a
  prior revision of this docstring overstated this as "every rename reloads
  regardless of reference form", which conflated the helper's own logic with
  `switch_as_x`'s particular callback choice. What the helper itself actually
  does (`helper_integration.py`'s `async_registry_updated`, the "entity_id"
  in `data["changes"]` branch) is form-dependent: for a **plain entity_id**
  reference, it calls the caller-supplied `set_source_entity_id_or_uuid`
  callback and does *not* itself reload — whether that callback reloads is
  up to the caller (`switch_as_x`'s own callback happens to call
  `hass.config_entries.async_schedule_reload` anyway, but that is
  `switch_as_x`'s choice, not something the helper forces). For a **registry
  UUID** reference, the helper *unconditionally* calls
  `await hass.config_entries.async_reload(helper_config_entry_id)` itself —
  not customizable via callback. This integration's own recommended and
  default persisted form is the UUID (design §6.4: "pin the UUID, because it
  survives entity_id renames unconditionally"), so the helper's
  unconditional-reload path is the one that actually matters for Entity
  Role's own common case — the practical cost is real, just for the
  UUID-pinned case specifically, not "every rename" as a blanket claim. This
  integration's own `_handle_source_relinked` below instead relinks the
  *same, already-running* entity instance in place for *both* reference
  forms, with no reload at all. Adopting the helper for UI-owned roles would
  be a concrete behavioral regression on rename for the UUID-pinned (default)
  case relative to what this integration already does and already tests
  (`tests/test_availability_unbound.py`; `_handle_source_relinked`'s own
  docstring).

Decision: retain this integration's own unified listener for both
configuration sources. The structural reason is the strongest one: the
helper's mandatory config-entry-scoping means it can never serve a
YAML-owned role, so adopting it only for UI-owned roles would introduce
exactly the source-conditional runtime behavior design §10.3 names as a
design smell ("every behavioral rule is defined on the role record, never
on its configuration source") — a UI-owned role bound by this integration's
own default (UUID) reference form would reload on every rename while a
YAML-owned role, on the identical event, would not. The compatibility
burden accepted by not adopting it: this integration keeps
maintaining its own registry-event handling rather than inheriting future
core-side fixes/improvements to the shared helper, mitigated the same way
the design's own risk register already covers general helper-API churn
(R22) — CI against both HA `stable` and `dev`.

**Device linkage (PLAT-130, design §4):** implemented below as
`_sync_device_link`, called from every path that can change what a role is
bound to (initial bind in `async_added_to_hass`, `async_rebind`,
`_handle_source_relinked`, and the device-only branch of
`_handle_registry_event`) — not via the add-time `device_info`/
`device_entry` mechanism `switch_as_x`'s own `BaseEntity.__init__` uses.
Verified directly against a real, current `home-assistant/core` `dev` clone
(`git clone --depth 1 --branch dev`, fetched 2026-09-02):
`helpers/entity_platform.py::EntityPlatform._async_add_entity` only honors
`entity.device_info`/`entity.device_entry` when `self.config_entry` is set —
for any entity added without one (`_check_device_attach`, lines ~839-852) it
silently forces `device_entry = None` and logs a deprecation report instead.
Every YAML-owned role goes through exactly that no-config-entry path
(`discovery.async_load_platform`, design §6.1), so the add-time mechanism
cannot serve both configuration sources uniformly — using it would be
precisely the source-conditional behavior design §10.3 calls a smell.

`entity_registry.async_update_entity(entity_id, device_id=...)` has no such
restriction: `_validate_item` only checks that the target device exists, not
that the entity has a config entry. That is also the exact call
`helper_integration.async_handle_source_entity_changes` itself uses to
relink on a source device move — so this integration mirrors that one
mechanic (a plain post-hoc registry write) behind its own unified,
source-agnostic call site, rather than adopting the whole config-entry-scoped
helper, per this ticket's own instruction. The role's own registry entry
starts with `device_id=None` at construction (RoleEntity never sets
`device_entry`/`device_info`) and is promoted/demoted afterward by
`_sync_device_link` alone — for both configuration sources, through the same
code path, so it is inherently symmetric rather than something that must be
kept in sync by hand. The role never creates or owns a device: every write
either points at an already-existing device the source itself belongs to, or
clears the link to `None`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import Context, Event, State, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_entity_registry_updated_event,
    async_track_state_change_event,
)

from .const import (
    DATA_FORWARD_CHAINS,
    DEFAULT_HIDE_SOURCE,
    DOMAIN,
    ISSUE_UNBOUND,
    ISSUE_UNBOUND_FIXABLE,
)
from .helpers import async_resolve_source_ref
from .hide import async_hide_source, async_migrate_expose_settings, async_unhide_source

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
        hide_source: bool = DEFAULT_HIDE_SOURCE,
        *,
        object_id: str | None = None,
    ) -> None:
        self._role_id = role_id
        self._role_domain = role_domain
        self._attr_unique_id = role_id
        self._attr_name = name
        # `object_id`, when given, pins the *first-creation* entity_id
        # independently of `name` — see the `suggested_object_id` override
        # below for why this exists (PLAT-150 carry-forward finding).
        self._object_id = object_id
        # `source_ref` is the persisted reference (registry UUID or plain
        # entity_id) as configured; `source_entity_id` is its resolution at
        # last (re)bind. They are re-reconciled on every registry event —
        # see _handle_registry_event.
        self._source_ref: str | None = source_ref if source_ref is not None else source_entity_id
        self._source_entity_id = source_entity_id
        self._contract = dict(contract)
        self._hide_source = hide_source
        self._source_state: State | None = None
        self._remove_state_listener: Callable[[], None] | None = None
        self._remove_registry_listener: Callable[[], None] | None = None

    @property
    def suggested_object_id(self) -> str | None:
        """Pin the entity_id a *newly-created* role registers under to
        `role_id` when the caller provided one, instead of Home Assistant's
        stock behavior of deriving it from `name` (`Entity.suggested_object_id`
        slugifies `self.name`) — PLAT-150 carry-forward finding.

        Only affects first-time registration: `entity_registry.async_get_or_
        create` looks up an *existing* entry by `unique_id` before ever
        consulting this property, so a role's entity_id — once assigned —
        stays fixed across every later reconcile/rebind regardless of this
        override (design §4's stability guarantee is otherwise untouched).

        Why this matters *because of* PLAT-150 specifically: before `name`
        was required, every YAML record without one fell back to
        `name = role_id` (see the removed `record.get("name", record[
        CONF_ROLE_ID])` in each platform's `from_yaml_record`), which meant
        `suggested_object_id`'s stock name-derived slug coincidentally
        equaled `role_id` in practice for every record this suite's own
        fixtures ever exercised (e.g. `name: "Kitchen Counter"` already
        slugifies back to `role_id: kitchen_counter`). With `name` now a
        genuinely independent, human-chosen string, a differently-worded
        `name` (e.g. `role_id: office_light`, `name: "Family Room Light"`)
        would otherwise register under `light.family_room_light` on first
        creation instead of the author-declared `light.office_light` —
        breaking design §4's "YAML-owned role: an author-declared role_id
        slug" identity guarantee and the Git-managed-determinism promise
        (design §6.3: "bindings converge to Git with no dependence on
        .storage") this integration's own tests already assert (see
        tests/test_identity.py). Only the YAML construction path
        (`from_yaml_record` classmethods) passes `object_id`; the UI/
        config-entry path deliberately keeps deriving the object id from
        the user-entered name, as it always has — a config-entry role's
        `role_id` is `entry.entry_id` (an opaque UUID), never meant to
        appear in an entity_id.
        """
        if self._object_id is not None:
            return self._object_id
        return super().suggested_object_id

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
    def hide_source(self) -> bool:
        return self._hide_source

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
            self._apply_hide_source_policy(old_source_entity_id=None)
        # Unconditional, not just in the bound branch above (PLAT-151): a
        # role constructed unbound (predeclared, or a role_id whose record
        # lost its `source` across a cold restart — DATA_YAML_ROLES resets
        # then, so this is a fresh construction, not an async_rebind) may
        # still own a *stale* device_id from a prior bound registry entry
        # under the same unique_id. _sync_device_link is idempotent/cheap
        # (a no-op when the target already matches, e.g. the genuinely
        # brand-new-role case where it is already None) and is the only
        # thing here that both matters and is safe to run while unbound —
        # unlike issue-deletion (there is no ISSUE_UNBOUND to clear for a
        # role that was never bound) and hide-source policy (nothing to
        # hide without a source), it must actively clear a link that can
        # otherwise dangle.
        self._sync_device_link()

    def _apply_hide_source_policy(self, *, old_source_entity_id: str | None) -> None:
        """Hide the newly-bound source and migrate its expose settings onto
        this role; unhide a previous source no longer bound (design §10.1 R1
        / carry-forward item 3).

        Called both from async_added_to_hass (initial bind for either
        configuration source — `old_source_entity_id` is always None there,
        since a freshly-constructed entity has no prior binding of its own)
        and from async_rebind (every subsequent rebind for either source,
        where the caller still knows the actual previous source). The UI
        options flow's "unhide the old source" step is handled separately,
        in config_flow.py's `_apply_rebind`, *before* the options-change
        reload that tears down and reconstructs this entity — a fresh
        instance never learns what its predecessor was bound to, so that
        specific step cannot live here for the UI path.

        Idempotent by construction (hiding an already-hidden entity, or
        re-migrating identical settings, is a no-op), so this runs
        unconditionally on every add rather than tracking "was this
        genuinely the first bind" as separate persisted state — the accepted
        simplification is that a plain reload with an unchanged source
        re-copies the source's current settings onto the role, which would
        overwrite a manual expose-setting change made directly on the role
        afterward. Documented rather than silently accepted: this integration
        does not currently distinguish that case from a real rebind.
        """
        if not self._hide_source or self.hass is None:
            return
        if (
            old_source_entity_id is not None
            and old_source_entity_id != self._source_entity_id
        ):
            async_unhide_source(self.hass, old_source_entity_id)
        if self._source_entity_id is not None and self._source_entity_id != old_source_entity_id:
            async_hide_source(self.hass, self._source_entity_id)
            if self.entity_id:
                async_migrate_expose_settings(
                    self.hass, self._source_entity_id, self.entity_id
                )

    def _sync_device_link(self) -> None:
        """Link this role's registry device_id to its bound source's device
        (design §4), or clear it when unbound or the source itself has none.

        See the module docstring for why this goes through
        `entity_registry.async_update_entity` — the same config-entry-
        agnostic mechanic `helper_integration.async_handle_source_entity_
        changes` itself uses to relink — rather than the add-time
        `device_info`/`device_entry` mechanism, which `entity_platform.py`
        only honors for a role backed by a config entry (i.e. never for a
        YAML-owned one). Never creates or owns a device: `source_device_id`
        below is read from the source's own current registry entry, never
        synthesized, so a write here only ever points at an already-existing
        device or clears the link.

        Idempotent by construction (only writes when the value actually
        differs), matching `_apply_hide_source_policy`'s own pattern — safe
        to call unconditionally from every bind/rebind/relink path below,
        including a registry event on the source that turned out to be
        unrelated (e.g. an area/name change, where source_device_id is
        already equal to what this role's entry already carries).
        """
        if self.hass is None or not self.entity_id:
            return
        registry = er.async_get(self.hass)
        role_entry = registry.async_get(self.entity_id)
        if role_entry is None:
            return
        source_device_id = None
        if self._source_entity_id is not None:
            source_entry = registry.async_get(self._source_entity_id)
            source_device_id = source_entry.device_id if source_entry else None
        if role_entry.device_id != source_device_id:
            registry.async_update_entity(self.entity_id, device_id=source_device_id)

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

        That same entity_id-only re-resolution can't by itself notice the
        source being moved to a different HA device (design §4) — the
        source's entity_id, which is all `resolved` reflects, does not
        change when only its device does. `_sync_device_link` is therefore
        always resynced below, including on the "unrelated" branch, rather
        than special-cased on `event.data["changes"]` containing
        "device_id" — cheap (idempotent, one registry read) and keeps this
        listener's payload-shape independence intact.
        """
        if self._source_ref is None:
            return
        resolved = async_resolve_source_ref(self.hass, self._source_ref)
        if resolved == self._source_entity_id:
            self._sync_device_link()
            return  # otherwise unrelated registry change (e.g. area/name)
        if resolved is None:
            self.hass.async_create_task(self._handle_source_unbound())
        else:
            self.hass.async_create_task(self._handle_source_relinked(resolved))

    async def _handle_source_unbound(self) -> None:
        """Source removed from the registry (design §8): survive, go
        unavailable, and raise a repair issue.

        For a UI-owned role (a config entry backs this platform instance),
        the issue is fixable and deep-links straight into a "pick a
        replacement" flow (repairs.py::UnboundSourceFixFlow) — PLAT-128
        carry-forward item 4, previously UNVERIFIED in the design (§10.2
        #26) and unimplemented in the spike. A YAML-owned role has no
        entry_id and no config/options flow to deep-link into at all — its
        fix is "edit the file and reload", so its issue stays informational
        (is_fixable=False), exactly as before.
        """
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
            is_fixable=entry_id is not None,
            severity=ir.IssueSeverity.WARNING,
            # Two distinct translation keys, not one used with a
            # conditionally-present fix_flow — see const.py's
            # ISSUE_UNBOUND_FIXABLE comment for why.
            translation_key=ISSUE_UNBOUND_FIXABLE if entry_id is not None else ISSUE_UNBOUND,
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
        self._sync_device_link()
        self.async_write_ha_state()

    # -- rebind / unbind --------------------------------------------------------

    async def async_rebind(
        self,
        new_source_ref: str | None,
        new_contract: dict[str, Any] | None = None,
        new_hide_source: bool | None = None,
    ) -> None:
        """Rebind (or unbind, if new_source_ref is None) this role.

        Identity (unique_id/entity_id) never changes. Accepts the same
        reference form as configuration (registry UUID or entity_id);
        resolves it exactly as at initial bind. Called from the options
        flow (UI path) and from YAML reconciliation (declarative path) —
        both configuration sources converge on this one method, per the
        "one role model" rule in design §6.1/§10.3.

        `new_hide_source`, when given, updates the role's hide_source policy
        (e.g. a YAML record changing its `hide_source:` key on reload)
        before the new binding's hide/migrate is applied; omitted (None)
        leaves the current policy unchanged, which is what a UI rebind
        (hide_source is not itself editable from the replace-hardware step)
        always does.
        """
        old_source_entity_id = self._source_entity_id
        if new_hide_source is not None:
            self._hide_source = new_hide_source
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
        self._apply_hide_source_policy(old_source_entity_id=old_source_entity_id)
        self._sync_device_link()
        if self.hass is not None:
            ir.async_delete_issue(self.hass, DOMAIN, f"{ISSUE_UNBOUND}_{self._role_id}")
            self.async_write_ha_state()

    def async_update_contract(self, contract: dict[str, Any]) -> None:
        self._contract = dict(contract)

    # -- capability contract (design §5: advertise contract ∩ source) -----------

    def contract_intersect_iterable(self, key: str, source_value: Any) -> list[Any]:
        """Set-valued capability: advertise contract ∩ source, e.g. color modes.

        While unbound (PLAT-151: `self._source_entity_id is None`, not merely
        the transient case of a bound source whose state hasn't loaded yet)
        there is no hardware to intersect against at all — advertise the
        declared contract's own value directly rather than collapsing to
        nothing, so a predeclared role's intended capabilities are visible
        (e.g. to HomeKit bridge setup) before a source is ever attached. This
        applies identically whether the role was predeclared unbound from
        the start or lost a previously-bound source (`_handle_source_
        unbound`) — both are the same "no source" shape, and design §10.3
        rules out defining this behavior differently depending on how that
        shape was reached.
        """
        contract_value = self._contract.get(key)
        if not contract_value:
            return []
        if self._source_entity_id is None:
            return sorted(set(contract_value))
        if source_value is None:
            return []
        return sorted(set(contract_value) & set(source_value))

    def contract_intersect_bitmask(self, key: str, source_value: int | None) -> int:
        """Bitmask-valued capability: advertise contract & source.

        See contract_intersect_iterable's docstring — the same unbound
        fallback applies here.
        """
        contract_value = self._contract.get(key, 0) or 0
        if self._source_entity_id is None:
            return int(contract_value)
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
