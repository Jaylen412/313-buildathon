"""Unit tests for signals.geo: Esri-ring parsing and the parcel -> block-group
spatial join, against tiny synthetic geometry. See md/architecture.md §8.
"""
from __future__ import annotations

import json

import duckdb
import pytest
from shapely.geometry import Polygon

from signals import geo
from signals.config import Settings

# Esri winds exterior rings clockwise, holes counter-clockwise. Winding
# direction (not vertex order) is what the shoelace formula picks up, so
# these two must trace opposite directions around the same kind of square.
SQUARE_CW = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]  # up, right, down, left = CW, area 100
HOLE_CCW = [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]]  # right, up, left, down = CCW, area 16


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=str(tmp_path))


def test_esri_rings_to_geometry_simple_square():
    geom = geo.esri_rings_to_geometry([SQUARE_CW])
    assert isinstance(geom, Polygon)
    assert geom.area == pytest.approx(100.0)
    assert len(geom.interiors) == 0


def test_esri_rings_to_geometry_with_hole():
    geom = geo.esri_rings_to_geometry([SQUARE_CW, HOLE_CCW])
    assert isinstance(geom, Polygon)
    assert len(geom.interiors) == 1
    assert geom.area == pytest.approx(100.0 - 16.0)


def test_esri_rings_to_geometry_multipart():
    second_square = [[20, 0], [20, 5], [25, 5], [25, 0], [20, 0]]
    geom = geo.esri_rings_to_geometry([SQUARE_CW, second_square])
    assert geom.geom_type == "MultiPolygon"
    assert geom.area == pytest.approx(100.0 + 25.0)


def test_esri_rings_to_geometry_orphan_hole_is_dropped():
    # A malformed/degenerate input: a hole ring with no preceding exterior.
    geom = geo.esri_rings_to_geometry([HOLE_CCW, SQUARE_CW])
    assert isinstance(geom, Polygon)
    assert geom.area == pytest.approx(100.0)  # the orphan hole was ignored


def _make_db_with_two_adjacent_block_groups() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    bg_a = [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]  # unit square, x in [0,1]
    bg_b = [[1, 0], [1, 1], [2, 1], [2, 0], [1, 0]]  # unit square, x in [1,2]
    con.execute(
        "CREATE TABLE raw_blockgroups (GEOID VARCHAR, geometry_json VARCHAR)"
    )
    con.execute(
        "INSERT INTO raw_blockgroups VALUES (?, ?), (?, ?)",
        ["A", json.dumps({"rings": [bg_a]}), "B", json.dumps({"rings": [bg_b]})],
    )
    con.execute(
        "CREATE TABLE raw_parcels (parcel_id VARCHAR, centroid_lon DOUBLE, centroid_lat DOUBLE)"
    )
    con.execute(
        "INSERT INTO raw_parcels VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?), (?, ?, ?)",
        [
            "p_in_a", 0.5, 0.5,
            "p_in_b", 1.5, 0.5,
            "p_outside", 9.0, 9.0,
            "p_null_centroid", None, None,
        ],
    )
    return con


def test_assign_block_groups_matches_points_to_polygons():
    con = _make_db_with_two_adjacent_block_groups()
    result = geo.assign_block_groups(con)

    by_id = result.set_index("parcel_id")["bg_geoid"].to_dict()
    assert by_id["p_in_a"] == "A"
    assert by_id["p_in_b"] == "B"
    assert pd_isna(by_id["p_outside"])
    # p_null_centroid was excluded entirely (no centroid to join on)
    assert "p_null_centroid" not in by_id

    # parcel_geo table was written and is queryable
    rows = con.execute("SELECT count(*) FROM parcel_geo").fetchone()[0]
    assert rows == 3


def pd_isna(value) -> bool:
    import pandas as pd

    return pd.isna(value)


def test_export_blockgroups_geojson_writes_file_and_returns_featurecollection(tmp_path):
    con = _make_db_with_two_adjacent_block_groups()
    settings = _settings(tmp_path)
    result = geo.export_blockgroups_geojson(con, settings=settings)

    assert result["type"] == "FeatureCollection"
    geoids = {f["properties"]["bg_geoid"] for f in result["features"]}
    assert geoids == {"A", "B"}

    out_file = tmp_path / "blockgroups.geojson"
    assert out_file.exists()
    on_disk = json.loads(out_file.read_text())
    assert on_disk == result
