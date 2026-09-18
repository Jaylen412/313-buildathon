"""Demo-mode helpers: corridor presets and household anonymization.

GEOIDs below are placeholders — fill them in once md/TODO.md item D.1 (pick
two hot corridors + one control area) is done and the map is live.
"""
from __future__ import annotations

import re

# block-group GEOIDs for the map's fly-to buttons. TODO(user): replace with
# real picks per md/TODO.md D.1, validated against the scored map.
DEMO_CORRIDORS: dict[str, list[str]] = {
    "hot_1": [],  # e.g. Hubbard Richard / Corktown edge
    "hot_2": [],  # e.g. McDougall-Hunt / Poletown East
    "control": [],  # a stable, flat-permit neighborhood
}

_LEADING_NUMBER = re.compile(r"^\s*(\d+)\s+(.*)$")

# Fields that identify a person or a single parcel. Never leave the server
# in demo mode.
IDENTIFYING_FIELDS = ("parcel_id", "owner")


def hundred_block(address: str | None) -> str:
    """'1234 VINEWOOD ST' -> '1200 block of VINEWOOD ST'. Addresses without
    a leading number are returned as 'block of <street>' with no number."""
    m = _LEADING_NUMBER.match(address or "")
    if not m:
        return f"block of {(address or '').strip()}".strip()
    number, street = int(m.group(1)), m.group(2).strip()
    return f"{(number // 100) * 100} block of {street}"


def anonymize_household(household: dict) -> dict:
    """Strip identifying fields for SIGNALS_DEMO=1: drop names and parcel_id,
    reduce the address to its hundred-block. Reasons are kept — they carry
    no names."""
    out = {k: v for k, v in household.items() if k not in IDENTIFYING_FIELDS}
    out["address"] = hundred_block(household.get("address"))
    return out
