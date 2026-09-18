"""DuckDB connection + schema DDL. See md/architecture.md §5 for the data model."""
from __future__ import annotations

import duckdb

from signals.config import Settings, get_settings

SCHEMA = """
-- raw_* tables are created dynamically by ingest.py from the pulled parquet
-- (their columns mirror sources.py out_fields). Everything below is derived.

CREATE TABLE IF NOT EXISTS parcel_geo (
    parcel_id   VARCHAR PRIMARY KEY,
    bg_geoid    VARCHAR,
    lon         DOUBLE,
    lat         DOUBLE
);

CREATE TABLE IF NOT EXISTS sales_clean (
    sale_id                 BIGINT,
    parcel_id               VARCHAR,
    sale_date               DATE,
    amt_sale_price          DOUBLE,
    ppsf                    DOUBLE,
    is_llc_buyer            BOOLEAN,
    is_out_of_state_buyer   BOOLEAN,
    bg_geoid                VARCHAR
);

CREATE TABLE IF NOT EXISTS bg_features (
    bg_geoid                    VARCHAR,
    year                        INTEGER,
    n_sales                     INTEGER,
    median_price                DOUBLE,
    median_ppsf                 DOUBLE,
    price_yoy                   DOUBLE,
    llc_share                   DOUBLE,
    out_of_state_share          DOUBLE,
    permit_count                INTEGER,
    permit_value                DOUBLE,
    new_construction_permits    INTEGER,
    permit_count_yoy            DOUBLE,
    blight_tickets               INTEGER,
    vacant_share                 DOUBLE,
    owner_occ_share               DOUBLE,
    dist_to_hot_corridor_m        DOUBLE,
    PRIMARY KEY (bg_geoid, year)
);

CREATE TABLE IF NOT EXISTS bg_scores (
    bg_geoid            VARCHAR PRIMARY KEY,
    heat_score           INTEGER,
    predicted_growth      DOUBLE,
    confidence            VARCHAR,   -- 'ok' | 'low' (< 3 sales in the scoring year)
    top_signals            JSON,
    model_version           VARCHAR,
    model_mode              VARCHAR,
    scored_at               TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parcel_vulnerability (
    parcel_id       VARCHAR PRIMARY KEY,
    bg_geoid        VARCHAR,
    rank            INTEGER,
    score           DOUBLE,
    reasons         JSON,
    heirship_flag   BOOLEAN,
    computed_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS briefs (
    bg_geoid        VARCHAR,
    model_version   VARCHAR,
    brief           JSON,
    created_at      TIMESTAMP,
    PRIMARY KEY (bg_geoid, model_version)
);
"""


def connect(settings: Settings | None = None) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the project DuckDB file and ensure the derived
    schema exists. Raw tables are created separately by ingest.load_all()."""
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.db_path))
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute(SCHEMA)
    return con
