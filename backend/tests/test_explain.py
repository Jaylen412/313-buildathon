"""Explainer tests: the aggregate-only input, the strict output schema, the
prompt rules that were learned from real data, and the file cache. No network —
the OpenAI client is injected, following tests/test_brief.py.
"""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from signals import explain
from signals.config import PROTECTIONS, Settings

THIS_YEAR = date.today().year


def _detail() -> dict:
    return {
        "name": "Bethune Community",
        "slug": "bethune-community",
        "n_block_groups": 9,
        "n_hot": 6,
        "heat_max": 98,
        "heat_mean": 72,
        "hottest_geoid": "261635101001",
        "n_low_confidence": 0,
        "hot_threshold": 70,
        "model_mode": "trained",
        "scored_at": "2026-09-18T00:00:00+00:00",
        "backtest_summary": "model hgb-v1 · backtest on 2023: Spearman ρ = 0.39, R² = 0.11",
        "top_signals": [
            {"feature": "price_yoy", "label": "sale prices vs. the year before",
             "direction": "mixed", "mean_z": -0.28, "n_members": 9,
             "n_block_groups": 9, "n_up": 4, "n_down": 5},
            {"feature": "llc_share", "label": "share of sales bought by LLCs / investors",
             "direction": "up", "mean_z": 1.06, "n_members": 6,
             "n_block_groups": 9, "n_up": 6, "n_down": 0},
        ],
        "trend": {
            "years": [2019, 2020, 2021, 2022, 2023, 2024, 2025, THIS_YEAR],
            "series": {
                "n_sales": [100.0, 120.0, 159.0, 180.0, 190.0, 204.0, 194.0, 90.0],
                "median_ppsf": [20.0, 28.0, 35.72, 40.0, 44.0, 51.89, 48.25, 50.0],
                "median_price": [1.0] * 8,
                "llc_share": [0.7, 0.68, 0.65, 0.6, 0.52, 0.55, 0.57, 0.58],
                "permit_count": [60.0, 62.0, 75.0, 65.0, 74.0, 68.0, 71.0, 30.0],
                "permit_value": [1.0] * 8,
                "blight_tickets": [900.0, 1000.0, 1200.0, 1500.0, 2011.0, 1391.0, 1605.0, 700.0],
            },
            "partial_year": THIS_YEAR,
        },
        "block_groups": [{"bg_geoid": "261635101001", "heat_score": 98, "confidence": "ok", "top_signals": []}],
    }


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(
        explain.store, "neighborhood_detail",
        lambda con, slug, report, threshold=70: _detail() if slug == "bethune-community" else None,
    )


PARAGRAPH = (
    "Investors are buying a growing share of the homes that sell in Bethune Community. "
    "There were 194 sales last year at a median of $48 per square foot, up from $36 in 2021, "
    "and investors took a larger share than is typical for the city in six of the nine block "
    "groups here. Six of those nine are above the pressure threshold, which is a forecast of "
    "where money is heading rather than a measure of who is being displaced."
)


def _explainer(summary: str = PARAGRAPH) -> explain.MetricExplainer:
    return explain.MetricExplainer(summary=summary)


class FakeResponses:
    def __init__(self, result: explain.MetricExplainer):
        self.result = result
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.result)


def _fake_client(result: explain.MetricExplainer | None = None):
    return SimpleNamespace(responses=FakeResponses(result or _explainer()))


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=str(tmp_path), OPENAI_MODEL="test-model", OPENAI_API_KEY="k")


# --------------------------------------------------------------------------- summary

def test_summary_is_aggregate_only(patched):
    summary = explain.build_neighborhood_summary(None, "bethune-community", None)
    payload = json.dumps(summary.model_dump())
    for leak in ("bg_geoid", "parcel_id", "address", "taxpayer", "household", "261635101001"):
        assert leak not in payload, f"{leak} reached the model"


def test_summary_drops_the_partial_year_and_keeps_five(patched):
    summary = explain.build_neighborhood_summary(None, "bethune-community", None)
    assert summary.trend_years == [2021, 2022, 2023, 2024, 2025]
    assert THIS_YEAR not in summary.trend_years
    assert set(summary.trend) == set(explain.TREND_METRICS)
    assert len(summary.trend["n_sales"]) == 5


def test_summary_carries_mixed_signal_counts(patched):
    summary = explain.build_neighborhood_summary(None, "bethune-community", None)
    mixed = next(s for s in summary.top_signals if s.feature == "price_yoy")
    assert mixed.direction == "mixed"
    assert (mixed.n_up, mixed.n_down, mixed.n_block_groups) == (4, 5, 9)


def test_summary_unknown_slug_is_none(patched):
    assert explain.build_neighborhood_summary(None, "nowhere", None) is None


# --------------------------------------------------------------------------- generation

def test_generate_uses_the_strict_schema(patched, tmp_path):
    summary = explain.build_neighborhood_summary(None, "bethune-community", None)
    client = _fake_client()
    out = explain.generate_explainer(summary, _settings(tmp_path), client)
    call = client.responses.calls[0]
    assert call["text_format"] is explain.MetricExplainer
    assert call["model"] == "test-model"
    assert out.summary.startswith("Investors are buying")


def test_generate_raises_when_the_model_returns_nothing(patched, tmp_path):
    summary = explain.build_neighborhood_summary(None, "bethune-community", None)
    client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kw: SimpleNamespace(output_parsed=None)))
    with pytest.raises(RuntimeError, match="no parsable summary"):
        explain.generate_explainer(summary, _settings(tmp_path), client)


def test_missing_api_key_is_a_clear_error(patched, tmp_path):
    summary = explain.build_neighborhood_summary(None, "bethune-community", None)
    settings = Settings(_env_file=None, DATA_DIR=str(tmp_path))
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        explain.generate_explainer(summary, settings)


# --------------------------------------------------------------------------- prompt hygiene

def test_prompt_carries_the_cross_sectional_rule():
    # brief.py rule 4: z-scores compare to the city in the same year, they are
    # not a change over time. Losing this makes the model narrate fiction.
    assert "NOT a change over time" in explain.SYSTEM_PROMPT
    assert "do not describe it as prices falling" in explain.SYSTEM_PROMPT
    assert "thin-market swing the model expects to reverse" in explain.SYSTEM_PROMPT


def test_prompt_forbids_neighborhood_level_z_scores():
    assert "never quote `mean_z`" in explain.SYSTEM_PROMPT
    assert "not a statistic about this" in explain.SYSTEM_PROMPT
    # mixed directions must be spoken as a split, never rounded to one side
    assert "the picture is split" in explain.SYSTEM_PROMPT
    assert "never pick" in explain.SYSTEM_PROMPT


def test_prompt_forbids_recommending_programs():
    assert "Do NOT recommend" in explain.SYSTEM_PROMPT
    # the sharpest statement that this is not the outreach brief: none of the
    # vetted protections are even named here
    for protection in PROTECTIONS:
        assert protection["name"] not in explain.SYSTEM_PROMPT


def test_prompt_bans_model_diagnostics_and_first_person():
    assert "no Spearman, no R squared" in explain.SYSTEM_PROMPT
    assert "Never describe the model or yourself" in explain.SYSTEM_PROMPT
    assert 'no "I"' in explain.SYSTEM_PROMPT


def test_prompt_bans_the_tools_own_vocabulary():
    # the first real calls narrated "heat mean 72, hot threshold 70" and
    # "investor share was 0.16" at people who just want plain English
    assert "Never use the tool's" in explain.SYSTEM_PROMPT
    for jargon in ('"hot threshold"', '"heat mean"', '"flagged"', '"signal"'):
        assert jargon in explain.SYSTEM_PROMPT
    assert 'percentages, never decimals' in explain.SYSTEM_PROMPT


def test_output_is_a_single_paragraph():
    assert list(explain.MetricExplainer.model_fields) == ["summary"]
    out = _explainer()
    assert "\n" not in out.summary
    assert "- " not in out.summary


def test_prompt_asks_for_one_paragraph():
    assert "ONE paragraph of ordinary prose" in explain.SYSTEM_PROMPT
    assert "three or four sentences" in explain.SYSTEM_PROMPT
    for banned in ("bullet points", "numbered lists", "line breaks"):
        assert banned in explain.SYSTEM_PROMPT


def test_program_mentions_are_stripped_sentence_by_sentence():
    name = PROTECTIONS[0]["name"]
    planted = _explainer(
        f"Investor share is climbing here. Tell them about {name} right away. "
        "Permits have held steady for three years."
    )
    cleaned = explain._drop_program_mentions(planted)
    assert name not in cleaned.summary
    # the surrounding sentences survive — one stray mention must not blank the summary
    assert "Investor share is climbing here." in cleaned.summary
    assert "Permits have held steady for three years." in cleaned.summary


def test_program_stripping_survives_punctuation():
    name = PROTECTIONS[0]["name"]
    mangled = name.replace(" ", "-").replace(chr(39), "")
    planted = _explainer(f"Prices are rising. Consider {mangled} for these owners.")
    cleaned = explain._drop_program_mentions(planted)
    assert cleaned.summary == "Prices are rising."


# --------------------------------------------------------------------------- cache

def test_cache_miss_then_hit(patched, tmp_path):
    settings = _settings(tmp_path)
    client = _fake_client()
    first = explain.get_or_create_explainer(None, "bethune-community", None, settings, client)
    assert first is not None and first[1] is False
    assert len(client.responses.calls) == 1

    second = explain.get_or_create_explainer(None, "bethune-community", None, settings, client)
    assert second is not None and second[1] is True
    assert len(client.responses.calls) == 1, "a cache hit must not call the provider"

    forced = explain.get_or_create_explainer(None, "bethune-community", None, settings, client, force=True)
    assert forced is not None and forced[1] is False
    assert len(client.responses.calls) == 2


def test_cache_file_records_the_summary_it_was_built_from(patched, tmp_path):
    settings = _settings(tmp_path)
    explain.get_or_create_explainer(None, "bethune-community", None, settings, _fake_client())
    path = explain.cache_path(settings, "bethune-community", "trained")
    saved = json.loads(path.read_text())
    assert saved["slug"] == "bethune-community"
    assert saved["name"] == "Bethune Community"
    assert saved["llm_model"] == "test-model"
    assert saved["summary"]["n_hot"] == 6
    assert saved["explainer"]["summary"].startswith("Investors are buying")


def test_unknown_slug_returns_none_without_calling_the_provider(patched, tmp_path):
    client = _fake_client()
    assert explain.get_or_create_explainer(None, "nowhere", None, _settings(tmp_path), client) is None
    assert client.responses.calls == []


def test_a_cache_from_an_older_schema_is_regenerated(patched, tmp_path):
    settings = _settings(tmp_path)
    path = explain.cache_path(settings, "bethune-community", "trained")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"explainer": {"headline": "old shape", "caveats": []}}))
    client = _fake_client()
    result = explain.get_or_create_explainer(None, "bethune-community", None, settings, client)
    assert result is not None
    explainer, cached, _ = result
    assert cached is False, "an unreadable cache must regenerate"
    assert explainer.summary.startswith("Investors are buying")


def test_prompt_forbids_approximating_block_group_counts():
    # a real call said "seven of ten block groups" where the summary said eight
    assert "Counts are exact" in explain.SYSTEM_PROMPT
    assert "never round it" in explain.SYSTEM_PROMPT


def test_prompt_separates_neighborhood_totals_from_per_block_counts():
    # a real call attributed the neighborhood's 1,437 blight tickets to "one part"
    assert "describes the WHOLE neighborhood" in explain.SYSTEM_PROMPT
    assert "never attribute one to a part" in explain.SYSTEM_PROMPT
