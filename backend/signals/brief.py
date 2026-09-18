"""LLM outreach brief (OpenAI). Interpretation only — it explains the score,
it never computes it. See md/CLAUDE.md "Non-negotiable design constraints".

Contract (md/architecture.md §6):
    generate_brief(summary: BlockSummary) -> Brief

Build order milestone: step 7 (Brief). Not yet implemented.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from signals.config import PROTECTIONS, get_settings


class BlockSummary(BaseModel):
    """Everything the LLM is allowed to see and cite — aggregate only, no
    household rows. Passed in to generate_brief()."""

    bg_geoid: str
    neighborhood: str
    heat_score: int
    top_signals: list[dict]
    trend: dict[str, list[float]]
    n_owner_occupied: int
    n_flagged_households: int
    reason_counts: dict[str, int]


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
    caveats: list[str] = Field(
        default_factory=lambda: [
            "Heirship signals are a flag for follow-up, not a legal determination."
        ]
    )


SYSTEM_PROMPT = f"""You write one-page outreach briefs for Detroit community \
development organizations from a structured block summary. You explain the \
numbers given to you; you never compute or invent a score, percentage, or \
dollar figure that is not in the summary. Only recommend protections from \
this vetted list: {[p["name"] for p in PROTECTIONS]}. Always state that \
heirship signals are a follow-up flag, not a determination."""


def generate_brief(summary: BlockSummary) -> Brief:
    """Calls the OpenAI Responses API with Structured Outputs
    (strict JSON schema from Brief.model_json_schema()) using
    settings.openai_model. Caches the result in the `briefs` table keyed by
    (bg_geoid, model_version)."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set (backend/.env) — see md/TODO.md section A"
        )
    raise NotImplementedError("brief.generate_brief: see md/architecture.md §6")
