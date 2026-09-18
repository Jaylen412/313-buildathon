"""ArcGIS REST pagination -> parquet -> raw_* DuckDB tables.

Contract (md/architecture.md §6):
    pull_layer(layer, since=None) -> Path      # writes data/raw/{layer.name}.parquet
    load_all(con, since=None, resume=False)    # parquet -> raw_* tables, normalizes parcel_id

Pagination is *keyset* on the layer's object-id field (`WHERE oid > last
ORDER BY oid`), not resultOffset. Measured live on the sales view
(2026-09-18): resultOffset takes 0.5 s at offset 0, 19 s at offset 300k,
and intermittently times out server-side with a generic 400 "Invalid query
parameters"; keyset returns the same 1,000 rows in 0.1 s at any depth.

PARCELS pulls centroids only (returnCentroid=true) rather than full
polygons — 378k polygons would make the pull far too slow, and geo.py only
needs a point per parcel. BLOCKGROUPS pulls full polygons (625 rows, needed
for the map) and stores them as raw Esri-JSON strings; geo.py does the
actual geometry parsing.
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
USER_AGENT = "signals-ingest/0.1 (313 Buildathon)"


def _base_where(layer: Layer, since: date | None) -> str:
    if since is not None and layer.date_field is not None:
        return f"{layer.date_field} >= DATE '{since.isoformat()}'"
    return "1=1"


def _build_params(layer: Layer, since: date | None, oid_field: str, last_oid: int | None) -> dict:
    where = _base_where(layer, since)
    if last_oid is not None:
        where = f"({where}) AND {oid_field} > {last_oid}"
    out_fields = list(layer.out_fields)
    if oid_field not in out_fields:
        out_fields.append(oid_field)
    params: dict = {
        "f": "json",
        "where": where,
        "outFields": ",".join(out_fields),
        "outSR": "4326",
        "orderByFields": f"{oid_field} ASC",
        "resultRecordCount": PAGE_SIZE,
        "returnGeometry": "true" if layer.return_geometry else "false",
    }
    if layer.return_centroid:
        params["returnCentroid"] = "true"
    return params


def _get_json(client: httpx.Client, layer: Layer, url: str, params: dict) -> dict:
    """GET with retry + exponential backoff. Raises on repeated failure or an
    ArcGIS-reported error payload (which comes back as HTTP 200)."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(url, params=params, timeout=TIMEOUT_S)
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


def _fetch_page(client: httpx.Client, layer: Layer, params: dict) -> dict:
    return _get_json(client, layer, layer.query_url, params)


def _object_id_field(client: httpx.Client, layer: Layer) -> str:
    """Read the layer's object-id field name from its metadata. It differs
    across Detroit's layers (`ObjectId` vs `OBJECTID`), so never hardcode."""
    meta = _get_json(client, layer, layer.layer_url, {"f": "json"})
    field = meta.get("objectIdField")
    if not field:
        raise RuntimeError(f"{layer.name}: layer metadata has no objectIdField")
    return field


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
    """Keyset-page through layer.query_url and write the combined result to
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
        oid_field = _object_id_field(client, layer)
        rows: list[dict] = []
        last_oid: int | None = None
        page = 0
        while True:
            params = _build_params(layer, since, oid_field, last_oid)
            data = _fetch_page(client, layer, params)
            features = data.get("features", [])
            rows.extend(_feature_to_row(f, layer) for f in features)
            if features:
                last_oid = max(f["attributes"][oid_field] for f in features)
            page += 1
            print(f"  [{layer.name}] page {page} +{len(features)} rows (total {len(rows)}, "
                  f"{oid_field} <= {last_oid})")
            if len(features) < PAGE_SIZE:
                break
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
        if oid_field not in columns:
            columns.append(oid_field)
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


def load_all(
    con,
    since: date | None = None,
    settings: Settings | None = None,
    resume: bool = False,
) -> None:
    """Pull every layer in sources.ALL_LAYERS and load each into a raw_{name}
    table, stripping the trailing '.' from parcel_id (see §1 gotchas).

    resume=True skips the network pull for any layer whose parquet already
    exists (it is still (re)loaded into DuckDB), so a crashed run picks up
    where it left off instead of re-pulling finished layers."""
    settings = settings or get_settings()
    started = datetime.now(timezone.utc)
    for layer in ALL_LAYERS:
        print(f"=== {layer.name} ===")
        path = settings.raw_dir / f"{layer.name}.parquet"
        if resume and path.exists():
            print(f"[{layer.name}] --resume: {path} exists, skipping pull")
        else:
            path = pull_layer(layer, since=since, settings=settings)
        _load_layer(con, layer, path, since)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"ingest done in {elapsed:.0f}s")
