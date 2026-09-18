"""Unit tests for signals.ingest: keyset paginator, retry, date coercion, and
the raw-table loader — all against a mocked ArcGIS transport / in-memory
DuckDB, no network calls. See md/architecture.md §8.
"""
from __future__ import annotations

from datetime import date

import duckdb
import httpx
import pandas as pd
import pytest

from signals import ingest
from signals.config import Settings
from signals.sources import ALL_LAYERS, Layer

SIMPLE_LAYER = Layer(
    name="things",
    service="things_service",
    date_field="issued_date",
    out_fields=["parcel_id", "issued_date", "amt"],
)

CENTROID_LAYER = Layer(
    name="parcels_test",
    service="parcels_service",
    return_centroid=True,
    out_fields=["parcel_id", "address"],
)

OID = "OBJECTID"


def _feature(oid: int, parcel_id: str, issued_date, amt: float) -> dict:
    return {"attributes": {OID: oid, "parcel_id": parcel_id, "issued_date": issued_date, "amt": amt}}


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=str(tmp_path))


def _is_metadata(request: httpx.Request) -> bool:
    return not request.url.path.endswith("/query")


def _metadata_response() -> httpx.Response:
    return httpx.Response(200, json={"objectIdField": OID})


def _client(query_handler) -> httpx.Client:
    """MockTransport that answers the metadata request itself and delegates
    /query requests to query_handler."""

    def handler(request: httpx.Request) -> httpx.Response:
        if _is_metadata(request):
            return _metadata_response()
        return query_handler(request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_keyset_paginates_until_short_page(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "PAGE_SIZE", 2)
    monkeypatch.setattr(ingest.time, "sleep", lambda _s: None)

    pages = [
        {"features": [_feature(10, "1.", "2024-01-01", 10), _feature(11, "2.", "2024-01-02", 20)]},
        {"features": [_feature(12, "3.", "2024-01-03", 30)]},  # short page -> stop
    ]
    seen_where: list[str] = []

    def query_handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen_where.append(params["where"])
        assert params["orderByFields"] == f"{OID} ASC"
        assert "resultOffset" not in params
        assert OID in params["outFields"].split(",")
        return httpx.Response(200, json=pages[len(seen_where) - 1])

    path = ingest.pull_layer(SIMPLE_LAYER, settings=_settings(tmp_path), client=_client(query_handler))

    # first page unconstrained, second page keyed past the max oid of page 1
    assert seen_where == ["1=1", f"(1=1) AND {OID} > 11"]
    df = pd.read_parquet(path)
    assert len(df) == 3
    assert list(df["parcel_id"]) == ["1.", "2.", "3."]  # trailing-dot stripped later, in _load_layer
    assert df["issued_date"].tolist() == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]


def test_since_filter_combines_with_keyset_where_clause():
    first = ingest._build_params(SIMPLE_LAYER, date(2025, 1, 1), OID, None)
    assert first["where"] == "issued_date >= DATE '2025-01-01'"
    later = ingest._build_params(SIMPLE_LAYER, date(2025, 1, 1), OID, 500)
    assert later["where"] == f"(issued_date >= DATE '2025-01-01') AND {OID} > 500"


def test_since_ignored_for_layers_without_date_field():
    params = ingest._build_params(CENTROID_LAYER, date(2025, 1, 1), OID, None)
    assert params["where"] == "1=1"


def test_object_id_field_read_from_layer_metadata():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"objectIdField": "ObjectId"})))
    assert ingest._object_id_field(client, SIMPLE_LAYER) == "ObjectId"


def test_centroid_extracted_into_columns(tmp_path):
    def query_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "attributes": {OID: 1, "parcel_id": "9.", "address": "1 Main St"},
                        "centroid": {"x": -83.05, "y": 42.33},
                    }
                ]
            },
        )

    path = ingest.pull_layer(CENTROID_LAYER, settings=_settings(tmp_path), client=_client(query_handler))
    df = pd.read_parquet(path)
    assert df.loc[0, "centroid_lon"] == pytest.approx(-83.05)
    assert df.loc[0, "centroid_lat"] == pytest.approx(42.33)


def test_empty_result_keeps_stable_schema(tmp_path):
    client = _client(lambda r: httpx.Response(200, json={"features": []}))
    path = ingest.pull_layer(SIMPLE_LAYER, settings=_settings(tmp_path), client=client)
    df = pd.read_parquet(path)
    assert len(df) == 0
    assert list(df.columns) == ["parcel_id", "issued_date", "amt", OID]


def test_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest.time, "sleep", lambda _s: None)
    query_attempts = {"n": 0}

    def query_handler(request: httpx.Request) -> httpx.Response:
        query_attempts["n"] += 1
        if query_attempts["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"features": [_feature(1, "5.", "2024-02-01", 5)]})

    path = ingest.pull_layer(SIMPLE_LAYER, settings=_settings(tmp_path), client=_client(query_handler))
    assert query_attempts["n"] == 3
    assert len(pd.read_parquet(path)) == 1


def test_gives_up_after_max_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest.time, "sleep", lambda _s: None)
    client = _client(lambda r: httpx.Response(500))
    with pytest.raises(RuntimeError, match="failed to fetch"):
        ingest.pull_layer(SIMPLE_LAYER, settings=_settings(tmp_path), client=client)


def test_arcgis_error_payload_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest.time, "sleep", lambda _s: None)
    client = _client(
        lambda r: httpx.Response(200, json={"error": {"code": 400, "message": "bad where clause"}})
    )
    with pytest.raises(RuntimeError, match="failed to fetch"):
        ingest.pull_layer(SIMPLE_LAYER, settings=_settings(tmp_path), client=client)


def test_coerce_date_field_handles_epoch_millis():
    df = pd.DataFrame({"issued_date": [1704067200000]})  # 2024-01-01 UTC
    out = ingest._coerce_date_field(df, SIMPLE_LAYER)
    assert out["issued_date"].iloc[0] == date(2024, 1, 1)


def test_coerce_date_field_handles_iso_strings():
    df = pd.DataFrame({"issued_date": ["2024-03-15"]})
    out = ingest._coerce_date_field(df, SIMPLE_LAYER)
    assert out["issued_date"].iloc[0] == date(2024, 3, 15)


def test_load_layer_strips_trailing_dot_from_parcel_id(tmp_path):
    parquet_path = tmp_path / "things.parquet"
    pd.DataFrame(
        {
            "parcel_id": ["21013863.", "12006336."],
            "issued_date": [date(2024, 1, 1), date(2024, 1, 2)],
            "amt": [1.0, 2.0],
        }
    ).to_parquet(parquet_path)

    con = duckdb.connect(":memory:")
    ingest._load_layer(con, SIMPLE_LAYER, parquet_path, since=None)

    rows = con.execute("SELECT parcel_id FROM raw_things ORDER BY parcel_id").fetchall()
    assert rows == [("12006336",), ("21013863",)]


def test_load_layer_incremental_refresh_replaces_only_the_window(tmp_path):
    con = duckdb.connect(":memory:")

    first = tmp_path / "things_1.parquet"
    pd.DataFrame(
        {
            "parcel_id": ["1.", "2."],
            "issued_date": [date(2024, 1, 1), date(2024, 6, 1)],
            "amt": [1.0, 2.0],
        }
    ).to_parquet(first)
    ingest._load_layer(con, SIMPLE_LAYER, first, since=None)

    # Incremental pull covering everything from 2024-06-01 onward: parcel "2"
    # should be replaced, parcel "1" (before the window) must survive.
    second = tmp_path / "things_2.parquet"
    pd.DataFrame(
        {
            "parcel_id": ["2.", "3."],
            "issued_date": [date(2024, 6, 1), date(2024, 7, 1)],
            "amt": [20.0, 30.0],
        }
    ).to_parquet(second)
    ingest._load_layer(con, SIMPLE_LAYER, second, since=date(2024, 6, 1))

    rows = con.execute("SELECT parcel_id, amt FROM raw_things ORDER BY parcel_id").fetchall()
    assert rows == [("1", 1.0), ("2", 20.0), ("3", 30.0)]


def test_load_all_calls_pull_and_load_for_every_layer(monkeypatch, tmp_path):
    pulled = []
    loaded = []

    def fake_pull_layer(layer, since=None, settings=None, client=None):
        pulled.append(layer.name)
        return tmp_path / f"{layer.name}.parquet"

    def fake_load_layer(con, layer, path, since):
        loaded.append(layer.name)

    monkeypatch.setattr(ingest, "pull_layer", fake_pull_layer)
    monkeypatch.setattr(ingest, "_load_layer", fake_load_layer)

    con = duckdb.connect(":memory:")
    ingest.load_all(con, settings=_settings(tmp_path))

    expected = [layer.name for layer in ALL_LAYERS]
    assert pulled == expected
    assert loaded == expected


def test_load_all_resume_skips_layers_with_existing_parquet(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    settings.raw_dir.mkdir(parents=True)
    (settings.raw_dir / f"{ALL_LAYERS[0].name}.parquet").write_bytes(b"")  # "already pulled"

    pulled, loaded = [], []
    monkeypatch.setattr(
        ingest, "pull_layer",
        lambda layer, since=None, settings=None, client=None: (pulled.append(layer.name), tmp_path / f"{layer.name}.parquet")[1],
    )
    monkeypatch.setattr(ingest, "_load_layer", lambda con, layer, path, since: loaded.append(layer.name))

    ingest.load_all(duckdb.connect(":memory:"), settings=settings, resume=True)

    names = [layer.name for layer in ALL_LAYERS]
    assert pulled == names[1:]  # first layer skipped
    assert loaded == names  # but still loaded into DuckDB
