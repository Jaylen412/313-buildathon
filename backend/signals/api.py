"""FastAPI app. Routes match md/architecture.md §6.

Household and brief routes are gated by X-Org-Token (spec's stand-in for
organization accounts — see md/TODO.md section A.2 for what that means).
Public routes never return parcel-level or household data.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException

from signals.config import get_settings

app = FastAPI(title="Signals API", version="0.1.0")


def require_org_token(x_org_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.signals_org_token:
        raise HTTPException(
            status_code=503,
            detail="SIGNALS_ORG_TOKEN is not configured on the server",
        )
    if x_org_token != settings.signals_org_token:
        raise HTTPException(status_code=403, detail="invalid or missing X-Org-Token")


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "model_mode": settings.model_mode.value,
        "geo_level": settings.geo_level.value,
        "demo": settings.signals_demo,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/blocks")
def list_blocks() -> dict:
    """Public: GeoJSON FeatureCollection of every scored block group
    (bg_geoid, heat_score, top_signals, neighborhood). Not yet implemented —
    depends on forecast.score() output (build order step 4-5)."""
    raise HTTPException(status_code=501, detail="not implemented: needs bg_scores")


@app.get("/api/blocks/{geoid}")
def get_block(geoid: str) -> dict:
    """Public: one block group's score, signals, and trend arrays."""
    raise HTTPException(status_code=501, detail="not implemented: needs bg_scores")


@app.get("/api/blocks/{geoid}/households")
def get_households(geoid: str, x_org_token: str | None = Header(default=None)) -> dict:
    """Gated: ranked households on a hot block group, anonymized in demo mode."""
    require_org_token(x_org_token)
    raise HTTPException(status_code=501, detail="not implemented: needs vulnerability.rank")


@app.post("/api/blocks/{geoid}/brief")
def post_brief(geoid: str, x_org_token: str | None = Header(default=None)) -> dict:
    """Gated: generate (or return cached) outreach brief for a block group."""
    require_org_token(x_org_token)
    raise HTTPException(status_code=501, detail="not implemented: needs brief.generate_brief")
