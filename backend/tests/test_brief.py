"""Unit tests for signals.brief: the aggregate-only summary, prompt hygiene,
protection enforcement, and the file cache — with a fake OpenAI client.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from signals import brief
from signals.config import PROTECTIONS, Settings
from signals.vulnerability import Household


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=str(tmp_path), OPENAI_API_KEY="sk-test", OPENAI_MODEL="test-model")


def _detail():
    return {
        "bg_geoid": "A", "neighborhood": "Hubbard Richard", "heat_score": 96, "confidence": "ok",
        "model_mode": "trained", "backtest_summary": "model hgb-v1 · backtest on 2023: Spearman ρ = 0.39, R² = 0.11",
        "top_signals": [{"feature": "llc_share", "label": "share of sales bought by LLCs / investors", "direction": "up", "z": 1.8, "value": 0.6, "weight": 0.01}],
        "trend": {"years": [2020, 2021, 2022, 2023, 2024, 2025, 2026], "partial_year": 2026,
                  "series": {"median_ppsf": [30, 32, 35, 40, 44, 50, 20], "n_sales": [5, 6, 7, 8, 9, 10, 2],
                             "llc_share": [0.2] * 7, "permit_count": [1] * 7, "blight_tickets": [3] * 7, "median_price": [1] * 7, "permit_value": [1] * 7}},
    }


def _households():
    mk = lambda pid, reasons, flag: Household(parcel_id=pid, bg_geoid="A", rank=1, score=5.0, reasons=reasons, heirship_flag=flag,
                                              address=f"{pid} MAIN ST", owner="PERSON, SOME", tenure_years=20, has_pre=False,
                                              unpaid_blight_balance=0, uncapping_gap=0.6)
    return [
        mk("1", ["No Principal Residence Exemption on file (mailing address matches the home)", "Owned 21+ years"], False),
        mk("2", ["Unpaid blight ticket balance $500 (delinquency proxy)", "Possible heirs' property: follow up, not a determination (estate/heirs wording in the taxpayer name)"], True),
        mk("3", ["No sale on record — likely long tenure", "Taxable value 80% below assessed — a transfer would spike the tax bill"], False),
    ]


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(brief.store, "block_detail", lambda con, g, r: _detail() if g == "A" else None)
    monkeypatch.setattr(brief.vulnerability, "is_hot", lambda con, g, t: True)
    monkeypatch.setattr(brief.vulnerability, "rank", lambda con, g, persist=True, **kw: _households())


class FakeResponses:
    def __init__(self, result: brief.Brief):
        self.result = result
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.result)


def _fake_client(result: brief.Brief):
    return SimpleNamespace(responses=FakeResponses(result))


def _brief(protections=None) -> brief.Brief:
    return brief.Brief(
        headline="Pressure is arriving on the east edge of Hubbard Richard",
        what_is_changing=["Investor purchases are above the city average."],
        why_it_matters="Long-tenured owners without an exemption face the biggest bills.",
        protections_to_offer=protections if protections is not None else [
            brief.Protection(name=PROTECTIONS[0]["name"], who_qualifies="Owner-occupants", first_step="Ask if they've filed the affidavit")
        ],
        canvassing_plan=["Start on the blocks nearest the corridor."],
        caveats=["Heirs'-property flags are a prompt for follow-up, not a determination."],
    )


def test_summary_is_aggregate_only_and_counts_reasons(patched):
    s = brief.build_block_summary(con=None, geoid="A", report={"model_version": "hgb-v1"})
    assert s.neighborhood == "Hubbard Richard" and s.heat_score == 96
    assert s.n_owner_occupied == 3 and s.n_flagged_households == 1
    assert s.reason_counts == {
        "missing_pre": 1, "unpaid_blight_balance": 1, "long_tenure": 1,
        "no_sale_on_record": 1, "uncapping_exposure": 1, "possible_heirs_property": 1,
    }
    # partial 2026 dropped, last five complete years kept
    assert s.trend_years == [2021, 2022, 2023, 2024, 2025]
    assert s.trend["median_ppsf"] == [32, 35, 40, 44, 50]
    assert "median_price" not in s.trend
    dumped = json.dumps(s.model_dump())
    assert "MAIN ST" not in dumped and "PERSON" not in dumped  # no household rows leak


def test_unknown_block_group_returns_none(patched):
    assert brief.build_block_summary(None, "nope", None) is None


def test_generate_brief_uses_strict_schema_and_prompt_rules(patched, tmp_path):
    settings = _settings(tmp_path)
    client = _fake_client(_brief())
    s = brief.build_block_summary(None, "A", {"model_version": "hgb-v1"})

    out = brief.generate_brief(s, settings, client)

    call = client.responses.calls[0]
    assert call["model"] == "test-model" and call["text_format"] is brief.Brief
    assert "never compute" in call["instructions"].lower() or "explain, never compute" in call["instructions"].lower()
    for p in PROTECTIONS:
        assert p["name"] in call["instructions"]
        assert p["who_qualifies"] in call["instructions"]  # vetted eligibility text travels with the name
    assert "NOT a change over time" in call["instructions"]
    assert '"heat_score": 96' in call["input"]
    assert out.headline.startswith("Pressure")


def test_unlisted_protection_is_dropped(patched, tmp_path):
    bad = brief.Protection(name="Magic Grant Program", who_qualifies="anyone", first_step="call")
    ok = brief.Protection(name="Pay As You Stay (PAYS)", who_qualifies="delinquent owner-occupants", first_step="check the treasurer's site")
    out = brief.generate_brief(brief.build_block_summary(None, "A", None), _settings(tmp_path), _fake_client(_brief([bad, ok])))
    assert [p.name for p in out.protections_to_offer] == ["Pay As You Stay (PAYS)"]


def test_get_or_create_brief_caches_to_file(patched, tmp_path):
    settings = _settings(tmp_path)
    client = _fake_client(_brief())
    report = {"model_version": "hgb-v1"}

    first, cached1, _ = brief.get_or_create_brief(None, "A", report, settings, client)
    second, cached2, _ = brief.get_or_create_brief(None, "A", report, settings, client)

    assert cached1 is False and cached2 is True
    assert first == second
    assert len(client.responses.calls) == 1  # second call served from cache
    path = brief.cache_path(settings, "A", "hgb-v1")
    assert path.exists()
    on_disk = json.loads(path.read_text())
    assert on_disk["llm_model"] == "test-model" and on_disk["brief"]["headline"] == first.headline

    forced, cached3, _ = brief.get_or_create_brief(None, "A", report, settings, client, force=True)
    assert cached3 is False and len(client.responses.calls) == 2


def test_missing_api_key_is_a_clear_error(patched, tmp_path):
    settings = Settings(_env_file=None, DATA_DIR=str(tmp_path))
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        brief.generate_brief(brief.build_block_summary(None, "A", None), settings)
