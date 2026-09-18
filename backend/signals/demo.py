"""Demo-mode helpers: corridor presets and household anonymization.

GEOIDs below are data-driven suggestions — confirm or replace them for md/TODO.md item D.1 (pick
two hot corridors + one control area) is done and the map is live.
"""
from __future__ import annotations

import re

# Block-group GEOIDs for the map's fly-to buttons (md/TODO.md D.1). These are
# DATA-DRIVEN SUGGESTIONS from the first real scoring run (2026-09-18) —
# replace them with your own picks and flip `suggested` to False. The API
# enriches each with its live neighborhood name and heat score.
DEMO_CORRIDORS: list[dict] = [
    {
        "key": "hot_1",
        "label": "Corridor 1 · Hubbard Richard",
        "bg_geoid": "261635211002",
        "why": "Corktown/Mexicantown edge: investors buying, next to the permit corridor; 167 owner-occupied homes, 44 missing a PRE.",
        "suggested": True,
    },
    {
        "key": "hot_2",
        "label": "Corridor 2 · McDougall-Hunt",
        "bg_geoid": "261635190002",
        "why": "Beside Eastern Market / Brush Park, where prices have already flipped; this block group hasn't yet.",
        "suggested": True,
    },
    {
        "key": "control",
        "label": "Control · University District",
        "bg_geoid": "261635384002",
        "why": "Stable, 70% owner-occupied, 20 sales a year, heat score in the single digits.",
        "suggested": True,
    },
]

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
