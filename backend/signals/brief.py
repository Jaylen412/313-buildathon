"""LLM outreach brief (OpenAI). Interpretation only — it explains the score,
it never computes it. See CLAUDE.md "Non-negotiable design constraints".

Contract (md/architecture.md §6):
    build_block_summary(con, geoid, report) -> BlockSummary   # aggregates only
    generate_brief(summary, settings=None, client=None) -> Brief
    get_or_create_brief(con, geoid, ...) -> (Brief, cached: bool)

The model sees a BlockSummary: the block group's score, its labelled
signals, five years of trend, and *counts* of household reasons. It never
sees a household row, a name, or an address. The system prompt forbids
inventing numbers and restricts protections to config.PROTECTIONS.

Briefs are cached as JSON files under data/briefs/ (keyed by GEOID + model
version + LLM model) rather than in DuckDB: the API holds a read-only
connection, and a file cache also survives a re-ingest. TODO.md E.4
("assume bad venue Wi-Fi") is served by the same cache — generate the demo
block groups' briefs beforehand and the demo never calls the network.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from signals import store, vulnerability
from signals.config import PROTECTIONS, Settings, get_settings

TREND_YEARS = 5
REASON_KEYS = {
    "missing_pre": "No Principal Residence Exemption",
    "unpaid_blight_balance": "Unpaid blight ticket balance",
    "long_tenure": "Owned",
    "no_sale_on_record": "No sale on record",
    "uncapping_exposure": "Taxable value",
    "possible_heirs_property": vulnerability.HEIRSHIP_REASON,
}


class SignalSummary(BaseModel):
    feature: str
    label: str
    direction: str
    z: float
    value: float | None = None


class BlockSummary(BaseModel):
    """Everything the LLM is allowed to see and cite — aggregate only, no
    household rows."""

    bg_geoid: str
    neighborhood: str | None
    heat_score: int
    confidence: str
    model_mode: str
    backtest_summary: str
    top_signals: list[SignalSummary]
    trend_years: list[int]
    trend: dict[str, list[float | None]]
    n_owner_occupied: int
    n_flagged_households: int
    reason_counts: dict[str, int]
    hot_threshold: int


class Protection(BaseModel):
    name: str
    who_qualifies: str
    first_step: str


class Brief(BaseModel):
    headline: str
    what_is_changing: list[str]
    why_it_matters: str
    protections_to_offer: list[Protection]
    canvassing_plan: list[str]
    caveats: list[str]


ALLOWED_PROTECTIONS = [p["name"] for p in PROTECTIONS]
PROTECTIONS_TEXT = "\n".join(f'   - {p["name"]}: who qualifies — {p["who_qualifies"]}' for p in PROTECTIONS)

SYSTEM_PROMPT = f"""You write one-page outreach briefs for Detroit community development
organizations (CDOs), land trusts, and housing counselors. Each brief covers one Census
block group flagged by a deterministic forecast of investment pressure.

Rules:
1. Explain, never compute. You are given a heat score, its top signals, a short trend,
   and counts of household risk factors. Do not invent, extrapolate, or restate any number
   that is not literally in the summary. If a figure is missing, say so rather than guess.
2. Only recommend protections from this vetted list, by these exact names, and describe
   who qualifies faithfully to the vetted text below — never broaden a program to a
   different problem:
{PROTECTIONS_TEXT}
   For each one you recommend, restate who qualifies in plain terms and give a concrete
   first step a canvasser can take at the door. Recommend only the ones the summary's
   reason counts make relevant (missing_pre -> PRE; unpaid_blight_balance is a *blight
   ticket* balance, not property-tax delinquency, so it does not by itself qualify anyone
   for PAYS or the Tax Relief Fund; possible_heirs_property -> heirs' property help).
3. Heirs'-property signals are a follow-up flag from a name heuristic, never a
   determination. Say that whenever you mention them.
4. How to read top_signals: each `direction`/`z` compares this block group to the rest of
   Detroit in the same year — "up" means above the city's typical value, "down" means below.
   It is NOT a change over time. So "distance to the nearest high-permit corridor — down"
   means this block group is closer to a permit hotspot than most of the city, not that it
   moved. Use the trend arrays (five complete years) for anything about change over time.
   "Sale prices vs. the year before — down" means last year's median sale price dipped
   relative to the city; in a block group with few sales that is usually a thin-market swing
   the model expects to reverse, not a decline in value. Do not describe it as prices
   falling.
5. Write for a canvasser who will read it on a phone: short sentences, no jargon, no
   marketing language, no exclamation points. Address the residents with respect. Do not
   quote z-scores, field names, or JSON keys, and do not explain how to read the data —
   just say what it means in plain words (e.g. "closer to a permit hotspot than most of the
   city", "investors bought a larger share of homes here than is typical").
6. The canvassing plan is about which doors to knock first and what to bring; it never
   names or singles out a household.
"""


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def _classify_reason(reason: str) -> str | None:
    for key, prefix in REASON_KEYS.items():
        if reason.startswith(prefix):
            return key
    return None


def build_block_summary(con, geoid: str, report: dict | None) -> BlockSummary | None:
    detail = store.block_detail(con, geoid, report)
    if detail is None:
        return None
    hot = vulnerability.is_hot(con, geoid, vulnerability.DEFAULT_HOT_THRESHOLD)
    households = vulnerability.rank(con, geoid, persist=False) if hot else []

    counts: dict[str, int] = {k: 0 for k in REASON_KEYS}
    for h in households:
        for r in h.reasons:
            key = _classify_reason(r)
            if key:
                counts[key] += 1

    years = detail["trend"]["years"]
    keep = [i for i, y in enumerate(years) if y != detail["trend"]["partial_year"]][-TREND_YEARS:]
    trend = {
        k: [v[i] for i in keep]
        for k, v in detail["trend"]["series"].items()
        if k in ("median_ppsf", "n_sales", "llc_share", "permit_count", "blight_tickets")
    }
    return BlockSummary(
        bg_geoid=geoid,
        neighborhood=detail["neighborhood"],
        heat_score=detail["heat_score"],
        confidence=detail["confidence"],
        model_mode=detail["model_mode"],
        backtest_summary=detail["backtest_summary"],
        top_signals=[
            SignalSummary(
                feature=s["feature"], label=s["label"], direction=s["direction"],
                z=round(s["z"], 1), value=None if s.get("value") is None else round(s["value"], 2),
            )
            for s in detail["top_signals"]
        ],
        trend_years=[years[i] for i in keep],
        trend=trend,
        n_owner_occupied=len(households),
        n_flagged_households=sum(h.heirship_flag for h in households),
        reason_counts=counts,
        hot_threshold=vulnerability.DEFAULT_HOT_THRESHOLD,
    )


def summary_to_prompt(summary: BlockSummary) -> str:
    return (
        "Block group summary (JSON). Every number you may cite is here; there are no others.\n"
        + json.dumps(summary.model_dump(), indent=1)
        + "\n\nWrite the outreach brief."
    )


# ---------------------------------------------------------------------------
# generation + cache
# ---------------------------------------------------------------------------

def openai_client(settings: Settings):
    """Shared by explain.py — keep it public."""
    from openai import OpenAI

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (backend/.env) — see md/TODO.md section A")
    return OpenAI(api_key=settings.openai_api_key)


def generate_brief(summary: BlockSummary, settings: Settings | None = None, client=None) -> Brief:
    """Calls the OpenAI Responses API with a strict schema derived from Brief
    (responses.parse + text_format) using settings.openai_model. `client` is
    injectable for tests."""
    settings = settings or get_settings()
    client = client or openai_client(settings)
    response = client.responses.parse(
        model=settings.openai_model,
        instructions=SYSTEM_PROMPT,
        input=summary_to_prompt(summary),
        text_format=Brief,
    )
    brief = response.output_parsed
    if brief is None:
        raise RuntimeError("the model returned no parsable brief")
    return _enforce_protections(brief)


def _enforce_protections(brief: Brief) -> Brief:
    """Belt and braces: drop any protection whose name isn't on the vetted
    list, even though the prompt forbids it."""
    allowed = {re.sub(r"\W+", "", n).lower() for n in ALLOWED_PROTECTIONS}
    brief.protections_to_offer = [
        p for p in brief.protections_to_offer if re.sub(r"\W+", "", p.name).lower() in allowed
    ]
    return brief


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def cache_path(settings: Settings, geoid: str, model_version: str) -> Path:
    return settings.data_dir / "briefs" / f"{_safe(geoid)}.{_safe(model_version)}.{_safe(settings.openai_model)}.json"


def get_or_create_brief(
    con, geoid: str, report: dict | None, settings: Settings | None = None,
    client=None, force: bool = False,
) -> tuple[Brief, bool, BlockSummary] | None:
    """Return (brief, cached, summary), generating and caching on a miss.
    None if the block group is unknown."""
    settings = settings or get_settings()
    summary = build_block_summary(con, geoid, report)
    if summary is None:
        return None
    model_version = report["model_version"] if report else summary.model_mode
    path = cache_path(settings, geoid, model_version)
    if path.exists() and not force:
        return Brief.model_validate(json.loads(path.read_text())["brief"]), True, summary

    brief = generate_brief(summary, settings, client)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "bg_geoid": geoid,
        "model_version": model_version,
        "llm_model": settings.openai_model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary.model_dump(),
        "brief": brief.model_dump(),
    }, indent=1))
    return brief, False, summary
