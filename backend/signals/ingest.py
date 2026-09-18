"""ArcGIS REST pagination -> parquet -> raw_* DuckDB tables.

Contract (md/architecture.md §6):
    pull_layer(layer, since=None) -> Path      # writes data/raw/{layer.name}.parquet
    load_all(con, since=None)                  # parquet -> raw_* tables, normalizes parcel_id

Every layer caps at 1,000 records/response (md/architecture.md §1), so this
pages with resultOffset until a short page signals the end. PARCELS pulls
centroids only (returnCentroid=true) rather than full polygons — 378k
polygons would make the pull far too slow, and geo.py only needs a point per
parcel. BLOCKGROUPS pulls full polygons (a few hundred rows, needed for the
map) and stores them as raw Esri-JSON strings; geo.py does the actual
geometry parsing.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

from signals.config import Settings, get_settings
from signals.sources import ALL_LAYERS, Layer

PAGE_SIZE = 1000
MAX_RETRIES = 5
TIMEOUT_S = 60.0
USER_AGENT = "signals-ingest/0.1 (313 Buildathon; +https://github.com/)"


def _build_params(layer: Layer, since: date | None, offset: int) -> dict:
    where = "1=1"
    if since is not None and layer.date_field is not None:
        where = f"{layer.date_field} >= DATE '{since.isoformat()}'"
    params: dict = {
        "f": "json",
        "where": where,
        "outFields": ",".join(layer.out_fields),
        "outSR": "4326",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
        "returnGeometry": "true" if layer.return_geometry else "false",
    }
    if layer.return_centroid:
        params["returnCentroid"] = "true"
    return params


def _fetch_page(client: httpx.Client, layer: Layer, params: dict) -> dict:
    """GET one page with retry + exponential backoff. Raises on repeated
    failure or an ArcGIS-reported error payload."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(layer.query_url, params=params, timeout=TIMEOUT_S)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
        else:
            if "error" in data:
                last_exc = RuntimeError(f"ArcGIS error for {layer.name}: {data['error']}")
            else:
                return data
        sleep_s = min(2**attempt, 20)
        print(f"  [{layer.name}] retry {attempt + 1}/{MAX_RETRIES} after {last_exc!r}, "
              f"sleeping {sleep_s}s")
        time.sleep(sleep_s)
    raise RuntimeError(f"failed to fetch {layer.name} after {MAX_RETRIES} attempts") from last_exc


def _feature_to_row(feature: dict, layer: Layer) -> dict:
    row = dict(feature.get("attributes", {}))
    if layer.return_centroid:
        centroid = feature.get("centroid") or {}
        row["centroid_lon"] = centroid.get("x")
        row["centroid_lat"] = centroid.get("y")
    if layer.return_geometry:
        geometry = feature.get("geometry")
        row["geometry_json"] = json.dumps(geometry) if geometry else None
    return row


def _coerce_date_field(df: pd.DataFrame, layer: Layer) -> pd.DataFrame:
    """Normalize layer.date_field to a plain date. ArcGIS serializes
    esriFieldTypeDateOnly fields as either 'YYYY-MM-DD' strings or epoch-ms
    integers depending on server config; handle both."""
    field = layer.date_field
    if not field or field not in df.columns or df[field].isna().all():
        return df
    if pd.api.types.is_numeric_dtype(df[field]):
        df[field] = pd.to_datetime(df[field], unit="ms", utc=True).dt.date
    else:
        df[field] = pd.to_datetime(df[field], errors="coerce").dt.date
    return df


def pull_layer(
    layer: Layer,
    since: date | None = None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """Page through layer.query_url and write the combined result to
    data/raw/{layer.name}.parquet. Idempotent: overwrites the existing file.
    Returns the parquet path.

    `client` is injectable (tests pass one backed by httpx.MockTransport);
    when omitted, a real client is opened and closed around the pull."""
    settings = settings or get_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    if owns_client:
        client = httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)

    try:
        rows: list[dict] = []
        offset = 0
        while True:
            params = _build_params(layer, since, offset)
            data = _fetch_page(client, layer, params)
            features = data.get("features", [])
            rows.extend(_feature_to_row(f, layer) for f in features)
            print(f"  [{layer.name}] offset={offset} +{len(features)} rows "
                  f"(total {len(rows)})")
            if len(features) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    finally:
        if owns_client:
            client.close()

    if rows:
        df = pd.DataFrame(rows)
        df = _coerce_date_field(df, layer)
    else:
        # Keep a stable schema even with zero rows (e.g. an incremental pull
        # that finds nothing new) so downstream SQL can still find parcel_id.
        columns = list(layer.out_fields)
        if layer.return_centroid:
            columns += ["centroid_lon", "centroid_lat"]
        if layer.return_geometry:
            columns += ["geometry_json"]
        df = pd.DataFrame(columns=columns)

    out_path = settings.raw_dir / f"{layer.name}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"[{layer.name}] wrote {len(df)} rows -> {out_path}")
    return out_path


def _load_layer(con, layer: Layer, parquet_path: Path, since: date | None) -> None:
    table = f"raw_{layer.name}"
    has_parcel_id = "parcel_id" in layer.out_fields
    # parquet path is always one we generated (settings.raw_dir / ...), never
    # user input, so inlining it (quoted) is safe and sidesteps DuckDB
    # parameter-binding quirks inside table functions.
    parquet_sql = parquet_path.as_posix().replace("'", "''")
    select_cols = (
        "* REPLACE (regexp_replace(CAST(parcel_id AS VARCHAR), '\\.$', '') AS parcel_id)"
        if has_parcel_id
        else "*"
    )
    select_sql = f"SELECT {select_cols} FROM read_parquet('{parquet_sql}')"

    table_exists = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()[0] > 0

    if since is not None and layer.date_field is not None and table_exists:
        # Incremental refresh: drop the overlapping window, then insert the
        # freshly pulled rows (which already carry the same >= since filter).
        con.execute(f"DELETE FROM {table} WHERE {layer.date_field} >= ?", [since])
        con.execute(f"INSERT INTO {table} {select_sql}")
    else:
        con.execute(f"CREATE OR REPLACE TABLE {table} AS {select_sql}")

    count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    print(f"[{layer.name}] {table}: {count} rows")


def load_all(con, since: date | None = None, settings: Settings | None = None) -> None:
    """Pull every layer in sources.ALL_LAYERS and load each into a raw_{name}
    table, stripping the trailing '.' from parcel_id (see §1 gotchas)."""
    settings = settings or get_settings()
    started = datetime.now(timezone.utc)
    for layer in ALL_LAYERS:
        print(f"=== {layer.name} ===")
        path = pull_layer(layer, since=since, settings=settings)
        _load_layer(con, layer, path, since)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"ingest done in {elapsed:.0f}s")
