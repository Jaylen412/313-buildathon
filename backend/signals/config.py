"""Runtime settings, loaded from environment variables / backend/.env.

See md/architecture.md §2 (Decisions) and §6 (config.py) for the contract.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class GeoLevel(str, Enum):
    """Geographic aggregation unit for scoring. Block group is the v1 default —
    see md/architecture.md §2 for why plain census blocks are too sparse."""

    BLOCK_GROUP = "block_group"
    BLOCK = "block"


class ModelMode(str, Enum):
    """Selects the forecast implementation. `auto` picks fallback when training
    rows are thin or the backtest is weak (see forecast.py)."""

    AUTO = "auto"
    TRAINED = "trained"
    FALLBACK = "fallback"


# Vetted protections the brief is allowed to recommend. Do not let the LLM
# invent entries outside this list — see md/TODO.md section D for the source
# of truth and md/architecture.md §6 (brief.py) for the constraint.
PROTECTIONS: list[dict[str, str]] = [
    {
        "name": "Principal Residence Exemption (PRE)",
        "who_qualifies": "Owner-occupants who have not filed a PRE affidavit with the Assessor.",
    },
    {
        "name": "HOPE (Homeowners Property Exemption)",
        "who_qualifies": "Low-income owner-occupants; reduces or eliminates property tax.",
    },
    {
        "name": "Pay As You Stay (PAYS)",
        "who_qualifies": "Owner-occupants with delinquent Wayne County property taxes.",
    },
    {
        "name": "Detroit Tax Relief Fund",
        "who_qualifies": "Owner-occupants who qualify for HOPE but need back-tax relief.",
    },
    {
        "name": "Heirs' property / probate assistance",
        "who_qualifies": "Households where the deed has not been updated after an owner's death.",
    },
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM (brief.py) ---
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5-mini", alias="OPENAI_MODEL")

    # --- stretch: Census ACS join ---
    census_api_key: str | None = Field(default=None, alias="CENSUS_API_KEY")

    # --- household gating (spec: org accounts stand-in) ---
    signals_org_token: str | None = Field(default=None, alias="SIGNALS_ORG_TOKEN")

    # --- demo mode: anonymize household output ---
    signals_demo: bool = Field(default=False, alias="SIGNALS_DEMO")

    # --- geography / modeling ---
    geo_level: GeoLevel = Field(default=GeoLevel.BLOCK_GROUP, alias="GEO_LEVEL")
    model_mode: ModelMode = Field(default=ModelMode.AUTO, alias="MODEL_MODE")

    # --- storage ---
    data_dir: Path = Field(default=BACKEND_ROOT / "data", alias="DATA_DIR")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "signals.duckdb"


@lru_cache
def get_settings() -> Settings:
    return Settings()
