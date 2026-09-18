"""FastAPI app. Routes match md/architecture.md §6.

Household and brief routes are gated by X-Org-Token (spec's stand-in for
organization accounts — see md/TODO.md section A.2 for what that means).
Public routes never return parcel-level or household data.

The API is read-only over the DuckDB file: it opens a read-only connection
per request (cheap, thread-safe, and always sees the latest `signals train`)
and caches the map payload keyed on the scores' timestamp.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock

import duckdb
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from signals import demo, store, vulnerability
from signals.config import get_settings
from signals.forecast import REPORT_FILENAME

app = FastAPI(title="Signals API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["X-Org-Token", "Content-Type"],
)


def get_con() -> duckdb.DuckDBPyConnection:
    """One read-only connection per request. Tests monkeypatch this."""
    path = get_settings().db_path
    if not path.exists():
        raise HTTPException(status_code=503, detail="no database yet: run `uv run signals ingest`")
    return duckdb.connect(str(path), read_only=True)


def load_report() -> dict | None:
    path = get_settings().models_dir / REPORT_FILENAME
    return json.loads(path.read_text()) if path.exists() else None


_blocks_cache: dict = {"stamp": None, "payload": None}
_blocks_lock = Lock()


def require_org_token(x_org_token: str | None) -> None:
    settings = get_settings()
    if not settings.signals_org_token:
        raise HTTPException(status_code=503, detail="SIGNALS_ORG_TOKEN is not configured on the server")
    if x_org_token != settings.signals_org_token:
        raise HTTPException(status_code=403, detail="invalid or missing X-Org-Token")


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    scored_at, n_scored, model_mode = None, 0, None
    if settings.db_path.exists():
        con = get_con()
        try:
            if store.scores_stamp(con):
                scored_at, n_scored, model_mode = con.execute(
                    "SELECT max(scored_at), count(*), any_value(model_mode) FROM bg_scores"
                ).fetchone()
                scored_at = scored_at.isoformat()
        finally:
            con.close()
    return {
        "ok": True,
        "configured_model_mode": settings.model_mode.value,
        "scored_model_mode": model_mode,
        "scored_at": scored_at,
        "n_scored": n_scored,
        "geo_level": settings.geo_level.value,
        "demo": settings.signals_demo,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/blocks")
def list_blocks() -> dict:
    """Public: GeoJSON FeatureCollection of every block group with its heat
    score, confidence, top signals and neighborhood name."""
    con = get_con()
    try:
        stamp = store.scores_stamp(con)
        if stamp is None:
            raise HTTPException(status_code=503, detail="not scored yet: run `uv run signals train`")
        with _blocks_lock:
            if _blocks_cache["stamp"] != stamp:
                geojson = get_settings().data_dir / "blockgroups.geojson"
                try:
                    payload = store.blocks_feature_collection(con, geojson)
                except FileNotFoundError as exc:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
                _blocks_cache.update(stamp=stamp, payload=payload)
            return _blocks_cache["payload"]
    finally:
        con.close()


@app.get("/api/blocks/{geoid}")
def get_block(geoid: str) -> dict:
    """Public: one block group's score, labelled signals, per-year trend, and
    the model footnote (backtest numbers or 'weighted index')."""
    con = get_con()
    try:
        try:
            detail = store.block_detail(con, geoid, load_report())
        except store.NotScoredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        con.close()
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown block group {geoid}")
    return detail


@app.get("/api/blocks/{geoid}/households")
def get_households(geoid: str, x_org_token: str | None = Header(default=None)) -> dict:
    """Gated: owner-occupied households on a hot block group, ranked by
    exposure with a reason per term. Computed live on the read-only
    connection (persist=False); anonymized when SIGNALS_DEMO=1. Block groups
    below the hot threshold return hot=false and no households."""
    require_org_token(x_org_token)
    settings = get_settings()
    con = get_con()
    try:
        if not store.scores_stamp(con):
            raise HTTPException(status_code=503, detail="not scored yet: run `uv run signals train`")
        if not con.execute("SELECT count(*) FROM bg_scores WHERE bg_geoid = ?", [geoid]).fetchone()[0]:
            raise HTTPException(status_code=404, detail=f"unknown block group {geoid}")
        hot = vulnerability.is_hot(con, geoid, vulnerability.DEFAULT_HOT_THRESHOLD)
        households = [h.to_dict() for h in vulnerability.rank(con, geoid, persist=False)] if hot else []
    finally:
        con.close()
    if settings.signals_demo:
        households = [demo.anonymize_household(h) for h in households]
    return {
        "bg_geoid": geoid,
        "hot": hot,
        "hot_threshold": vulnerability.DEFAULT_HOT_THRESHOLD,
        "anonymized": settings.signals_demo,
        "heirship_note": vulnerability.HEIRSHIP_REASON,
        "households": households,
    }


@app.post("/api/blocks/{geoid}/brief")
def post_brief(geoid: str, x_org_token: str | None = Header(default=None)) -> dict:
    """Gated: generate (or return cached) outreach brief for a block group."""
    require_org_token(x_org_token)
    raise HTTPException(status_code=501, detail="outreach briefs arrive in build step 7")
