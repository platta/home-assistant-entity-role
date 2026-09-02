"""Hide/unhide and repeated-rebind shuttling (design §10.1 R1, spike gate f
"repeated-rebind hide/expose shuttling").
"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.homeassistant import exposed_entities
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_HIDE_SOURCE,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DOMAIN,
)
from custom_components.entity_role.hide import (
    async_hide_source,
    async_migrate_expose_settings,
    async_unhide_source,
)
from custom_components.entity_role.yaml_config import async_reconcile_yaml_roles
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import create_source_entity, role_entity_id


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


async def test_migrate_expose_settings_copies_should_expose_and_unexposes_source(
    hass: HomeAssistant,
) -> None:
    """PLAT-128 carry-forward item 3: async_migrate_expose_settings against
    the real, verified exposed_entities module-level API (not the guessed,
    nonexistent object-returning shape the spike could not check) — copies
    each assistant's should_expose from source to role and un-exposes the
    source itself, mirroring switch_as_x's copy_expose_settings."""
    source = create_source_entity(hass, "light", "nanoleaf")
    exposed_entities.async_expose_entity(hass, "conversation", source, True)

    result = async_migrate_expose_settings(hass, source, "light.kitchen_counter")

    assert result is True
    role_settings = exposed_entities.async_get_entity_settings(hass, "light.kitchen_counter")
    assert role_settings["conversation"]["should_expose"] is True
    source_settings = exposed_entities.async_get_entity_settings(hass, source)
    assert source_settings["conversation"]["should_expose"] is False


async def test_ui_creation_hides_source_and_migrates_expose_settings(
    hass: HomeAssistant,
) -> None:
    """Regression test for a real PLAT-128 finding: the pre-fix call site
    passed the role's *display name* as the expose-migration target, not its
    entity_id — a string that can never resolve to a real entity, so
    migration silently never worked for any UI-created role. Exercised
    end-to-end through the real creation flow, not just the unit-level
    helper above, to prove the correct entity_id is what actually gets used
    now that RoleEntity._apply_hide_source_policy applies it from
    async_added_to_hass, where self.entity_id is real."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    exposed_entities.async_expose_entity(hass, "conversation", source, True)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ROLE_DOMAIN: "light"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Kitchen Counter", CONF_SOURCE: source}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.async_block_till_done()

    role_id = role_entity_id(hass, "light", entry.entry_id)
    assert er.async_get(hass).async_get(source).hidden_by == er.RegistryEntryHider.INTEGRATION
    role_settings = exposed_entities.async_get_entity_settings(hass, role_id)
    assert role_settings["conversation"]["should_expose"] is True
    source_settings = exposed_entities.async_get_entity_settings(hass, source)
    assert source_settings["conversation"]["should_expose"] is False


async def test_ui_creation_with_hide_source_false_does_not_hide_or_migrate(
    hass: HomeAssistant,
) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    exposed_entities.async_expose_entity(hass, "conversation", source, True)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Counter",
        data={CONF_ROLE_DOMAIN: "light"},
        options={
            CONF_SOURCE: source,
            CONF_CAPABILITY_CONTRACT: {},
            CONF_HIDE_SOURCE: False,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(source).hidden_by is None
    source_settings = exposed_entities.async_get_entity_settings(hass, source)
    assert source_settings["conversation"]["should_expose"] is True


async def test_yaml_role_hides_source_by_default(hass: HomeAssistant) -> None:
    """Regression test for a real PLAT-128 finding: yaml_config.py parsed
    and stored hide_source (default true, per the schema and README) but
    never actually called into hide.py at all — a YAML-declared role never
    hid its source no matter what hide_source said. Fixed by routing hide
    through RoleEntity.async_added_to_hass, driven by hide_source now being
    threaded into EntityRoleLight.from_yaml_record."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {DOMAIN: [{"role_id": "kitchen_counter", "role_domain": "light", "source": source}]},
    )
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(source).hidden_by == er.RegistryEntryHider.INTEGRATION


async def test_yaml_role_hide_source_false_leaves_source_visible(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    await async_reconcile_yaml_roles(
        hass,
        {
            DOMAIN: [
                {
                    "role_id": "kitchen_counter",
                    "role_domain": "light",
                    "source": source,
                    "hide_source": False,
                }
            ]
        },
    )
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(source).hidden_by is None
