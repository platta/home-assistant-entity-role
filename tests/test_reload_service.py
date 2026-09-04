"""entity_role.reload service — spike gate (d): reload without HA restart,
and the unparseable-file last-known-good behavior (design §10.1 R7).
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.entity_role.const import DOMAIN, SERVICE_RELOAD

from .conftest import create_source_entity


async def test_setup_registers_reload_service_even_without_yaml(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, SERVICE_RELOAD)


async def test_initial_yaml_config_creates_roles(hass: HomeAssistant) -> None:
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    assert await async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: [
                {
                    "role_id": "kitchen_counter",
                    "role_domain": "light",
                    "source": source,
                    "name": "Kitchen Counter",
                }
            ]
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("light.kitchen_counter") is not None


async def test_reload_service_picks_up_file_changes(hass: HomeAssistant) -> None:
    source_a = create_source_entity(hass, "light", "nanoleaf", state="on")
    assert await async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: [
                {
                    "role_id": "kitchen_counter",
                    "role_domain": "light",
                    "source": source_a,
                    "name": "Kitchen Counter",
                }
            ]
        },
    )
    await hass.async_block_till_done()

    source_b = create_source_entity(hass, "light", "hue", state="off")
    new_config = {
        DOMAIN: [
            {
                "role_id": "kitchen_counter",
                "role_domain": "light",
                "source": source_b,
                "name": "Kitchen Counter",
            }
        ]
    }

    with patch(
        "custom_components.entity_role.async_integration_yaml_config",
        return_value=new_config,
    ):
        await hass.services.async_call(DOMAIN, SERVICE_RELOAD, {}, blocking=True)
    await hass.async_block_till_done()

    assert hass.states.get("light.kitchen_counter").state == "off"


async def test_reload_with_unparseable_file_leaves_roles_untouched(hass: HomeAssistant) -> None:
    """design §10.1 R7: an unparseable/invalid file must not affect
    currently running roles — async_integration_yaml_config returning None
    is the verified stock signal for this
    (template/__init__.py::_reload_config, design §2.3/§10.1 R7)."""
    source = create_source_entity(hass, "light", "nanoleaf", state="on")
    assert await async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: [
                {
                    "role_id": "kitchen_counter",
                    "role_domain": "light",
                    "source": source,
                    "name": "Kitchen Counter",
                }
            ]
        },
    )
    await hass.async_block_till_done()

    with patch(
        "custom_components.entity_role.async_integration_yaml_config",
        return_value=None,
    ):
        await hass.services.async_call(DOMAIN, SERVICE_RELOAD, {}, blocking=True)
    await hass.async_block_till_done()

    assert hass.states.get("light.kitchen_counter") is not None
    assert hass.states.get("light.kitchen_counter").state == "on"
