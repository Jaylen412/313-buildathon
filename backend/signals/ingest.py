"""ArcGIS REST pagination -> parquet -> raw_* DuckDB tables.

Contract (md/architecture.md §6):
    pull_layer(layer, since=None) -> Path      # writes data/raw/{layer.name}.parquet
    load_all(con, since=None)                  # parquet -> raw_* tables, normalizes parcel_id

Build order milestone: step 2 (Ingest). Not yet implemented.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from signals.config import get_settings
from signals.sources import Layer


def pull_layer(layer: Layer, since: date | None = None) -> Path:
    """Page through `layer.query_url` with resultOffset/resultRecordCount=1000,
    retrying on transient errors, and write the combined result to
    data/raw/{layer.name}.parquet. Idempotent: overwrites the existing file."""
    raise NotImplementedError("ingest.pull_layer: see md/architecture.md §6")


def load_all(con: duckdb.DuckDBPyConnection, since: date | None = None) -> None:
    """Pull every layer in sources.ALL_LAYERS and load each into a raw_{name}
    table, stripping the trailing '.' from parcel_id (see §1 gotchas)."""
    raise NotImplementedError("ingest.load_all: see md/architecture.md §6")
