"""The Entity Role integration.

Accepts role definitions from two stock HA sources — config entries (the
community/UI path) and domain YAML (the declarative/GitOps path) — that
converge on identical runtime entities, per design §6.1. This module wires
up whichever source(s) are present: the YAML path and the `entity_role.reload`
service are always registered (mirroring `template`'s async_setup shape, so
the reload service exists even for an install with zero YAML — design
§2.3), while each config entry is forwarded to its own role_domain platform.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ROLE_DOMAIN, DOMAIN, SERVICE_RELOAD
from .yaml_config import ROLE_SCHEMA, async_reconcile_yaml_roles, async_setup_yaml

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.All(cv.ensure_list, [ROLE_SCHEMA])}, extra=vol.ALLOW_EXTRA
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await async_setup_yaml(hass, config)

    async def _handle_reload(call: ServiceCall) -> None:
        """Re-read entity_role: from YAML and reconcile running roles to it.

        design §10.1 R7 / spike gate (d): when the file is unparseable or
        fails the top-level schema, async_integration_yaml_config logs the
        failure and returns None *without* calling into reconciliation —
        every currently running role, YAML- or UI-owned, is left exactly as
        it was (last-known-good). Only a syntactically valid file reaches
        async_reconcile_yaml_roles, which then handles record-level
        invalidity itself (a bad record degrades only that role).
        """
        new_config = await async_integration_yaml_config(hass, DOMAIN)
        if new_config is None:
            _LOGGER.error(
                "entity_role.reload: configuration.yaml is invalid, "
                "leaving currently running roles unchanged"
            )
            return
        await async_reconcile_yaml_roles(hass, new_config)

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, _handle_reload)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    role_domain = entry.data[CONF_ROLE_DOMAIN]
    await hass.config_entries.async_forward_entry_setups(entry, [role_domain])
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    role_domain = entry.data[CONF_ROLE_DOMAIN]
    return await hass.config_entries.async_unload_platforms(entry, [role_domain])


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry whenever its options change.

    The manual equivalent of SchemaConfigFlowHandler's
    options_flow_reloads=True — see config_flow.py's module docstring for
    why this spike uses the manual flow base classes instead.
    """
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """No migrations yet — CONFIG_ENTRY_VERSION starts at 1 (design §8,
    "Config entry migration versioning from day one")."""
    return True
