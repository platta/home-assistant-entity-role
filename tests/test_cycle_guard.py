"""Command re-entrancy guard for indirect cycles (design §10.1 R3, spike gate g).

Direct role-on-role bindings are rejected at validation (see
test_source_validation.py); this covers the runtime guard for an indirect
cycle (role -> group/template -> the same role) that cannot be detected
statically from registry data alone, per the design's own analysis.
"""

from __future__ import annotations

import logging

from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DATA_FORWARD_CHAINS,
    DOMAIN,
)

from .conftest import create_source_entity


async def _setup_role(hass: HomeAssistant) -> tuple[MockConfigEntry, object]:
    source = create_source_entity(hass, "light", "nanoleaf", state="off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={CONF_SOURCE: source, CONF_CAPABILITY_CONTRACT: {}, "hide_source": False},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    role = hass.data[DOMAIN]["roles"][entry.entry_id]
    return entry, role


async def test_command_forwards_normally_without_cycle(hass: HomeAssistant) -> None:
    _, role = await _setup_role(hass)

    calls = []

    async def fake_turn_on(call):
        calls.append(call)

    hass.services.async_register("light", "turn_on", fake_turn_on)
    await role.async_forward_command("turn_on", {})
    assert len(calls) == 1


async def test_command_dropped_when_context_already_visited_this_role(
    hass: HomeAssistant, caplog
) -> None:
    """Simulate an indirect cycle: the incoming context has already passed
    through this role once (e.g. role -> group -> same role). The second
    pass must be dropped, not forwarded again, and must not raise."""
    _, role = await _setup_role(hass)

    calls = []

    async def fake_turn_on(call):
        calls.append(call)

    hass.services.async_register("light", "turn_on", fake_turn_on)

    context = Context()
    role._context = context  # the framework normally sets this from the incoming call
    hass.data[DOMAIN].setdefault(DATA_FORWARD_CHAINS, {})[context.id] = {role.role_id}

    with caplog.at_level(logging.ERROR):
        await role.async_forward_command("turn_on", {})

    assert len(calls) == 0
    assert "cycle guard" in caplog.text


async def test_chain_marker_cleared_after_forward_completes(hass: HomeAssistant) -> None:
    """A context's visited-set is cleaned up once forwarding for it
    finishes, so an unrelated later call with a *different* context is
    never affected by an earlier one."""
    _, role = await _setup_role(hass)
    hass.services.async_register("light", "turn_on", lambda call: None)

    await role.async_forward_command("turn_on", {})

    chains = hass.data[DOMAIN].get(DATA_FORWARD_CHAINS, {})
    assert chains == {}
