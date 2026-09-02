"""Constants for the Entity Role integration.

See docs/PLAT-125-hardware-role-abstraction-design.md (gitops repository,
merge commit af668725e9c632b12ba9c7dfc7c4e83df631250c) for the accepted
design this integration implements a bounded spike of.
"""

from __future__ import annotations

DOMAIN = "entity_role"

# Role record fields, shared by both configuration sources (config entry
# options and YAML) per design §6.1 — every field below means the same thing
# regardless of which source produced it.
CONF_ROLE_ID = "role_id"
CONF_ROLE_DOMAIN = "role_domain"
CONF_SOURCE = "source"
CONF_HIDE_SOURCE = "hide_source"
CONF_CAPABILITY_CONTRACT = "capability_contract"
CONF_DEVICE_CLASS = "device_class"

# Domains covered by this spike (design §1, §11): light prioritized, plus
# enough switch/binary_sensor coverage to validate the shared architecture.
DOMAIN_LIGHT = "light"
DOMAIN_SWITCH = "switch"
DOMAIN_BINARY_SENSOR = "binary_sensor"
SUPPORTED_DOMAINS = [DOMAIN_LIGHT, DOMAIN_SWITCH, DOMAIN_BINARY_SENSOR]

DEFAULT_HIDE_SOURCE = True

SERVICE_RELOAD = "reload"

CONFIG_ENTRY_VERSION = 1
YAML_SCHEMA_VERSION = 1

# Repair issue raised when a role's source is removed from the registry
# (design §8): the role survives, goes unavailable, and this issue deep-links
# the user back into the replace-hardware options step.
ISSUE_UNBOUND = "role_unbound"
# Raised for a syntax-valid YAML file containing one invalid record (design
# §10.1 R7 / spike gate d): the file as a whole is not rejected, only the
# broken role is flagged.
ISSUE_YAML_RECORD_INVALID = "yaml_record_invalid"

# hass.data storage keys.
DATA_ROLES = "roles"  # role_id -> RoleEntity, populated as entities register
DATA_FORWARD_CHAINS = "forward_chains"  # context.id -> set[role_id], cycle guard (R3)
DATA_YAML_ROLES = "yaml_roles"  # role_id -> role record, last-reconciled YAML state
