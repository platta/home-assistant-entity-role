"""Repair-issue integration for Entity Role.

Both issue types this integration raises (ISSUE_UNBOUND, entity.py; and
ISSUE_YAML_RECORD_INVALID, yaml_config.py) are created as `is_fixable=False`
today: they clear themselves automatically once the underlying condition is
resolved (rebind for the former, a corrected record for the latter — see
entity.py's async_rebind and yaml_config.py's per-reconcile issue clearing).

Design spike gate item #26 ("repairs deep-link into the rebind options
step") is explicitly marked UNVERIFIED in the accepted design itself
(§10.2 #26). This spike does not implement an inline repair-flow fix
button that opens the options flow directly — that deep-link mechanism
could not be verified against live core source in this sandbox — and
records the gate as PARTIAL rather than claiming it: the repair issue is
created/cleared correctly (verified by test), but the user's path from the
issue to a fix today is "open the role's Configure button", i.e. one extra
click versus an in-repair flow.
"""

from __future__ import annotations
