"""Demo-mode helpers: corridor presets and household anonymization.

GEOIDs below are placeholders — fill them in once md/TODO.md item D.1 (pick
two hot corridors + one control area) is done and the map is live.
"""
from __future__ import annotations

from signals.config import get_settings

# block-group GEOIDs for the map's fly-to buttons. TODO(user): replace with
# real picks per md/TODO.md D.1, validated against the scored map.
DEMO_CORRIDORS: dict[str, list[str]] = {
    "hot_1": [],  # e.g. Corktown / Core City
    "hot_2": [],  # e.g. Milwaukee Junction / North End
    "control": [],  # a stable, flat-permit neighborhood
}


def anonymize_household(household: dict) -> dict:
    """Strip identifying fields for SIGNALS_DEMO=1: drop names and parcel_id,
    reduce the address to its hundred-block (e.g. '1400 block of Vinewood St')."""
    settings = get_settings()
    if not settings.signals_demo:
        return household
    raise NotImplementedError("demo.anonymize_household: see md/architecture.md §6")
