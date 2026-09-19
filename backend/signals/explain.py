"""LLM metric explainer for a neighborhood (OpenAI). Interpretation only — it
explains numbers it is handed and never produces new ones. See CLAUDE.md
"Non-negotiable design constraints".

Contract (md/architecture.md §6):
    build_neighborhood_summary(con, slug, report) -> NeighborhoodSummary | None
    generate_explainer(summary, settings=None, client=None) -> MetricExplainer
    get_or_create_explainer(con, slug, report, ...) -> (MetricExplainer, cached, summary)

Output is a single natural-language paragraph, not a structured document: the
neighborhoods page already renders the figures, the aggregated signals and the
model footnote, so the paragraph's job is to say what they add up to.

Sibling of brief.py, deliberately separate: the brief is a canvassing document
that recommends vetted protections, this is a plain-language reading of the
metrics on the neighborhoods page. The two prompts pull in different
directions, so they don't share one.

The model sees a NeighborhoodSummary: the roll-up of the neighborhood's block
groups, its aggregated signals, and five complete years of trend. It never
sees a household row, a name, an address, or a parcel id — the same discipline
as brief.BlockSummary, and there is a test asserting it.

Explainers are cached as JSON files under data/explainers/ (keyed by slug +
model version + LLM model), like briefs, so a second click is instant and the
demo survives bad venue Wi-Fi (md/TODO.md E.4): `signals explain <slug…>`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from signals import store
from signals.brief import openai_client
from signals.config import PROTECTIONS, Settings, get_settings

TREND_YEARS = 5
TREND_METRICS = ("median_ppsf", "n_sales", "llc_share", "permit_count", "blight_tickets")


class AggregateSignal(BaseModel):
    """One signal rolled up across a neighborhood's block groups. `direction` is
    "up", "down" or "mixed" — mixed when the members genuinely disagree, which
    happens often enough on price_yoy that a majority-wins rule would publish
    claims true of no block group. `mean_z` is an average of separate
    cross-sectional comparisons and is NOT a z-score for the neighborhood."""

    feature: str
    label: str
    direction: str
    mean_z: float
    n_members: int
    n_block_groups: int
    n_up: int
    n_down: int


class NeighborhoodSummary(BaseModel):
    """Everything the LLM is allowed to see and cite — aggregate only."""

    name: str
    slug: str
    n_block_groups: int
    n_hot: int
    heat_max: int
    heat_mean: int
    n_low_confidence: int
    hot_threshold: int
    model_mode: str
    backtest_summary: str
    top_signals: list[AggregateSignal]
    trend_years: list[int]
    trend: dict[str, list[float | None]]


class MetricExplainer(BaseModel):
    """One paragraph of plain prose. Deliberately a single field: the page
    already shows the numbers, the signals and the footnotes, so the model's job
    is to say what they add up to — not to restate them as another list."""

    summary: str


FORBIDDEN_PROGRAMS = [p["name"] for p in PROTECTIONS]

SYSTEM_PROMPT = """You explain housing-market numbers to staff at Detroit community
development organizations, land trusts, and housing counselling agencies. You are given the
metrics behind one neighborhood's investment-pressure score — a score produced by a
deterministic model, not by you — and your only job is to say what those numbers mean in
plain English.

Rules:
1. Explain, never compute. Every figure you may cite is in the summary. Do not invent,
   extrapolate, average, or restate a number that is not literally there. If something is
   missing, say it is not available rather than guess. Never recompute or second-guess the
   score itself. Counts are exact: if you name a number of block groups it must be the
   `n_members` value as given — never round it, never approximate it, never say "seven of
   ten" where the summary says eight. Rounding a *price* to the nearest dollar is fine;
   rounding a count is an error.
2. How to read top_signals: each `direction` compares this neighborhood's block groups to
   the rest of Detroit in the same year — "up" means above the city's typical value, "down"
   means below. It is NOT a change over time. So "distance to the nearest high-permit
   corridor — down" means this neighborhood sits closer to a permit hotspot than most of the
   city, not that the distance shrank. "Sale prices vs. the year before — down" means last
   year's median sale price dipped relative to the city; where a neighborhood has few sales
   a year that is usually a thin-market swing the model expects to reverse, not a decline in
   value, so do not describe it as prices falling.
3. Never claim a neighborhood-wide amount above or below the city, and never quote `mean_z`
   — it averages separate per-block-group comparisons and is not a statistic about this
   place. Describe how widespread something is in words a person would use instead: "across
   most of the neighborhood", "in about half of it", "in one corner". You may anchor that
   with an explicit count ("six of its nine block groups") ONCE at most. A `direction` of
   "mixed" means the block groups disagree — say so ("the picture is split") and never pick
   a side.
4. Anything about change over time comes only from the trend arrays, which cover complete
   years. Use them for the story: what moved, over what span, and by how much. Every trend
   number describes the WHOLE neighborhood — counts are totals across all its block groups
   and medians are taken over all of its sales — so never attribute one to a part of it
   ("one corner had 1,437 blight tickets" is wrong when 1,437 is the neighborhood's total).
   How widespread something is comes only from the signals' block-group counts, and those
   two kinds of number must never be mixed in the same claim.
5. Do NOT recommend, name, or describe any assistance program, tax exemption, payment plan,
   legal service, or fund. That belongs to a separate outreach brief that uses a vetted list.
   Here you only explain what the numbers say.
6. Return ONE paragraph of ordinary prose: three or four sentences, 55 to 90 words. No
   headings, bullet points, numbered lists, line breaks or bold. Write the way a colleague
   who knows this city would sum it up out loud — plain, specific, unhurried. Someone who
   has not looked at the charts should follow it.
7. Say what the numbers add up to, not what they are. The figures, the signal list and the
   model's track record are already on the page beside your paragraph, so do not inventory
   them. Pick the two or three that carry the story, give the figure behind each, and say
   what they mean together. Lead with what is happening to the neighborhood.
8. Write numbers the way people say them: percentages, never decimals ("57%", not 0.57);
   whole dollars ("$48 a square foot", not 48.25); rounded counts. Never use the tool's
   vocabulary — no "heat", "hot threshold", "heat mean", "low-confidence block groups",
   "signal", "flagged", "up"/"down" as labels, no z-scores. If some block groups are
   low-confidence, put it in plain words ("two parts of the neighborhood had too few sales
   last year to read much into them"); if none are, do not mention confidence at all.
9. Never describe the model or yourself — no "the model flags", no Spearman, no R squared,
   no "I". Write about the place.
10. A rising score means money is moving toward the neighborhood. It is not a measure of
   displacement and says nothing about any individual resident. Carry that honestly in the
   prose rather than appending a disclaimer sentence.
"""


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def build_neighborhood_summary(
    con, slug: str, report: dict | None, hot_threshold: int = store.DEFAULT_HOT_THRESHOLD
) -> NeighborhoodSummary | None:
    detail = store.neighborhood_detail(con, slug, report, hot_threshold)
    if detail is None:
        return None
    years = detail["trend"]["years"]
    keep = [i for i, y in enumerate(years) if y != detail["trend"]["partial_year"]][-TREND_YEARS:]
    return NeighborhoodSummary(
        name=detail["name"],
        slug=detail["slug"],
        n_block_groups=detail["n_block_groups"],
        n_hot=detail["n_hot"],
        heat_max=detail["heat_max"],
        heat_mean=detail["heat_mean"],
        n_low_confidence=detail["n_low_confidence"],
        hot_threshold=detail["hot_threshold"],
        model_mode=detail["model_mode"],
        backtest_summary=detail["backtest_summary"],
        top_signals=[AggregateSignal(**s) for s in detail["top_signals"]],
        trend_years=[years[i] for i in keep],
        trend={
            k: [None if v[i] is None else round(v[i], 2) for i in keep]
            for k, v in detail["trend"]["series"].items()
            if k in TREND_METRICS
        },
    )


def summary_to_prompt(summary: NeighborhoodSummary) -> str:
    return (
        "Neighborhood metric summary (JSON). Every number you may cite is here; there are "
        "no others.\n"
        + json.dumps(summary.model_dump(), indent=1)
        + "\n\nExplain what these numbers mean."
    )


# ---------------------------------------------------------------------------
# generation + cache
# ---------------------------------------------------------------------------

def generate_explainer(
    summary: NeighborhoodSummary, settings: Settings | None = None, client=None
) -> MetricExplainer:
    """Calls the OpenAI Responses API with a strict schema derived from
    MetricExplainer. `client` is injectable for tests."""
    settings = settings or get_settings()
    client = client or openai_client(settings)
    response = client.responses.parse(
        model=settings.openai_model,
        instructions=SYSTEM_PROMPT,
        input=summary_to_prompt(summary),
        text_format=MetricExplainer,
    )
    explainer = response.output_parsed
    if explainer is None:
        raise RuntimeError("the model returned no parsable summary")
    return _drop_program_mentions(explainer)


def _normalize(s: str) -> str:
    return re.sub(r"\W+", "", s).lower()


def _drop_program_mentions(explainer: MetricExplainer) -> MetricExplainer:
    """Belt and braces for rule 5: drop any sentence that names a vetted
    assistance program. brief.py already learned that a prompt rule alone isn't
    enough (see brief._enforce_protections), and these programs' eligibility
    wording is only vetted in the brief's context — naming one here would be an
    unvetted recommendation. Sentence granularity rather than the whole
    paragraph, so one stray mention doesn't blank the summary."""
    banned = [_normalize(name) for name in FORBIDDEN_PROGRAMS]
    sentences = re.split(r"(?<=[.!?])\s+", explainer.summary.strip())
    kept = [s for s in sentences if not any(b in _normalize(s) for b in banned)]
    explainer.summary = " ".join(kept).strip()
    return explainer


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def cache_path(settings: Settings, slug: str, model_version: str) -> Path:
    return (
        settings.data_dir
        / "explainers"
        / f"{_safe(slug)}.{_safe(model_version)}.{_safe(settings.openai_model)}.json"
    )


def get_or_create_explainer(
    con,
    slug: str,
    report: dict | None,
    settings: Settings | None = None,
    client=None,
    force: bool = False,
    hot_threshold: int = store.DEFAULT_HOT_THRESHOLD,
) -> tuple[MetricExplainer, bool, NeighborhoodSummary] | None:
    """Return (explainer, cached, summary), generating and caching on a miss.
    None if the slug is unknown."""
    settings = settings or get_settings()
    summary = build_neighborhood_summary(con, slug, report, hot_threshold)
    if summary is None:
        return None
    model_version = report["model_version"] if report else summary.model_mode
    path = cache_path(settings, slug, model_version)
    if path.exists() and not force:
        try:
            cached = json.loads(path.read_text())
            return MetricExplainer.model_validate(cached["explainer"]), True, summary
        except (ValueError, KeyError):
            # written under an older output schema (or truncated) — fall through
            # and regenerate rather than failing the request
            pass

    explainer = generate_explainer(summary, settings, client)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "slug": slug,
        "name": summary.name,
        "model_version": model_version,
        "llm_model": settings.openai_model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary.model_dump(),
        "explainer": explainer.model_dump(),
    }, indent=1))
    return explainer, False, summary
