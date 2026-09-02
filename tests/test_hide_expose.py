"""Hide/unhide and repeated-rebind shuttling (design §10.1 R1, spike gate f
"repeated-rebind hide/expose shuttling").
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.entity_role.hide import async_hide_source, async_unhide_source

from .conftest import create_source_entity


async def test_hide_source_sets_hidden_by_integration(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf")
    async_hide_source(hass, source)
    entry = er.async_get(hass).async_get(source)
    assert entry.hidden_by == er.RegistryEntryHider.INTEGRATION


async def test_unhide_source_clears_hidden_by(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf")
    async_hide_source(hass, source)
    async_unhide_source(hass, source)
    entry = er.async_get(hass).async_get(source)
    assert entry.hidden_by is None


async def test_unhide_does_not_clear_a_user_hidden_entity(hass: HomeAssistant) -> None:
    """Only a hide this integration itself applied is reversed — an entity
    the user hid manually (hidden_by=USER) is left alone, since it was not
    this integration's to unhide."""
    source = create_source_entity(hass, "light", "nanoleaf")
    er.async_get(hass).async_update_entity(source, hidden_by=er.RegistryEntryHider.USER)

    async_unhide_source(hass, source)

    entry = er.async_get(hass).async_get(source)
    assert entry.hidden_by == er.RegistryEntryHider.USER


async def test_repeated_hide_unhide_shuttling_is_stable(hass: HomeAssistant) -> None:
    """Hide -> unhide -> hide -> unhide across repeated rebinds converges to
    the same state each time, with no accumulating side effect."""
    source = create_source_entity(hass, "light", "nanoleaf")

    for _ in range(3):
        async_hide_source(hass, source)
        assert er.async_get(hass).async_get(source).hidden_by == er.RegistryEntryHider.INTEGRATION
        async_unhide_source(hass, source)
        assert er.async_get(hass).async_get(source).hidden_by is None


async def test_hide_on_removed_entity_is_a_noop(hass: HomeAssistant) -> None:
    """Hiding/unhiding a source that is no longer registered (e.g. the
    rebind target of an already-orphaned reference) must not raise."""
    async_hide_source(hass, "light.does_not_exist")
    async_unhide_source(hass, "light.does_not_exist")
