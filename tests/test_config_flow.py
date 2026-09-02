"""The community creation and replace-hardware flows (design §7)."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.entity_role.const import (
    CONF_CAPABILITY_CONTRACT,
    CONF_ROLE_DOMAIN,
    CONF_SOURCE,
    DOMAIN,
)

from .conftest import create_source_entity


async def test_creation_flow_happy_path(hass: HomeAssistant) -> None:
    source = create_source_entity(
        hass,
        "light",
        "nanoleaf",
        state="on",
        attributes={"supported_color_modes": ["hs"], "supported_features": 0},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ROLE_DOMAIN: "light"}
    )
    assert result["step_id"] == "source"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Kitchen Counter", CONF_SOURCE: source}
    )
    assert result["step_id"] == "confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen Counter"
    assert result["data"][CONF_ROLE_DOMAIN] == "light"
    assert result["options"][CONF_SOURCE] == source
    assert set(result["options"][CONF_CAPABILITY_CONTRACT]["supported_color_modes"]) == {"hs"}

    await hass.async_block_till_done()
    assert hass.states.async_entity_ids("light") != []


async def test_creation_flow_source_step_uses_domain_filtered_selector(
    hass: HomeAssistant,
) -> None:
    """A cross-domain source is not a reachable error path through this flow
    at all: design §5 states domain mismatch is "impossible by construction
    in the UI (entity selector filtered to role_domain)" — the selector's
    own schema validation rejects it before this integration's code runs
    (confirmed by this spike's own CI: submitting one raises
    `data_entry_flow.InvalidData`, not a graceful form error). What this
    integration is responsible for is emitting that filtered selector in
    the first place."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ROLE_DOMAIN: "light"}
    )

    source_field = result["data_schema"].schema[CONF_SOURCE]
    # Confirmed by this spike's own CI: EntitySelectorConfig normalizes
    # "domain" to a plain string on HA stable but to a list on HA dev —
    # accept either rather than assuming one.
    domain_filter = source_field.config["domain"]
    if isinstance(domain_filter, str):
        domain_filter = [domain_filter]
    assert domain_filter == ["light"]


async def test_options_flow_replace_hardware_full_match(hass: HomeAssistant) -> None:
    source = create_source_entity(
        hass,
        "light",
        "nanoleaf",
        state="on",
        attributes={"supported_color_modes": ["hs"], "supported_features": 0},
    )
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

    replacement = create_source_entity(
        hass,
        "light",
        "hue",
        state="on",
        attributes={"supported_color_modes": ["hs"], "supported_features": 0},
    )

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    assert options_result["step_id"] == "replace_hardware"

    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"], {CONF_SOURCE: replacement}
    )
    assert options_result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_SOURCE] == replacement


async def test_options_flow_replace_hardware_downgrade_requires_confirmation(
    hass: HomeAssistant,
) -> None:
    source = create_source_entity(
        hass,
        "light",
        "nanoleaf",
        state="on",
        attributes={"supported_color_modes": ["hs", "color_temp"], "supported_features": 0},
    )
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

    downgraded = create_source_entity(
        hass,
        "light",
        "cheap_bulb",
        state="on",
        attributes={"supported_color_modes": ["brightness"], "supported_features": 0},
    )

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"], {CONF_SOURCE: downgraded}
    )
    assert options_result["step_id"] == "confirm_downgrade"
    assert "hs" in options_result["description_placeholders"]["lost_capabilities"]

    # Declining leaves the binding untouched.
    declined = await hass.config_entries.options.async_configure(
        options_result["flow_id"], {"confirm": False}
    )
    assert declined["step_id"] == "replace_hardware"
