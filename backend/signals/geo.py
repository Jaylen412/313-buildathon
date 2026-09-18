"""Parcel centroid -> block-group GEOID spatial join.

raw_parcels carries a lightweight centroid per parcel (ingest.py pulled it
with returnCentroid=true); raw_blockgroups carries full polygons as raw
Esri-JSON strings (ingest.py stores them as-is — this module owns turning
them into real geometry, per md/architecture.md §6).

Contract (md/architecture.md §6):
    assign_block_groups(con) -> None            # writes parcel_geo
    export_blockgroups_geojson(con) -> dict      # simplified polygons for the map
"""
from __future__ import annotations

import json

import duckdb
import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon

from signals.config import Settings, get_settings

# ~30m at Detroit's latitude — enough to shrink the map payload without
# visibly distorting block-group borders.
SIMPLIFY_TOLERANCE_DEG = 0.0003


def _ring_signed_area(ring: list[list[float]]) -> float:
    """Shoelace formula. Esri convention: exterior rings wind clockwise
    (negative signed area), holes counter-clockwise (positive)."""
    area = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def esri_rings_to_geometry(rings: list[list[list[float]]]) -> Polygon | MultiPolygon:
    """Esri polygon JSON gives a flat list of rings with no explicit
    exterior/hole grouping (unlike GeoJSON). Group each hole with the
    exterior ring that precedes it to rebuild proper (Multi)Polygons —
    handles both simple single-ring block groups and multi-part ones."""
    polygons: list[Polygon] = []
    exterior: list | None = None
    holes: list[list] = []
    for ring in rings:
        if _ring_signed_area(ring) < 0:  # clockwise -> a new exterior ring
            if exterior is not None:
                polygons.append(Polygon(exterior, holes))
            exterior, holes = ring, []
        else:  # counter-clockwise -> a hole in the current exterior
            if exterior is None:
                continue  # malformed input; drop an orphan hole rather than crash
            holes.append(ring)
    if exterior is not None:
        polygons.append(Polygon(exterior, holes))
    if not polygons:
        raise ValueError("esri_rings_to_geometry: no rings produced a valid polygon")
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


def _blockgroups_gdf(con: duckdb.DuckDBPyConnection) -> gpd.GeoDataFrame:
    df = con.execute(
        "SELECT GEOID AS bg_geoid, geometry_json FROM raw_blockgroups "
        "WHERE geometry_json IS NOT NULL"
    ).fetchdf()
    geometries = [esri_rings_to_geometry(json.loads(g)["rings"]) for g in df["geometry_json"]]
    return gpd.GeoDataFrame({"bg_geoid": df["bg_geoid"]}, geometry=geometries, crs="EPSG:4326")


def assign_block_groups(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """geopandas.sjoin of parcel centroids (raw_parcels.centroid_lon/lat)
    against raw_blockgroups polygons; writes one row per parcel to
    parcel_geo (parcel_id, bg_geoid, lon, lat). Parcels whose centroid falls
    outside every block-group polygon get bg_geoid=NULL rather than being
    dropped. Returns the written DataFrame."""
    blockgroups = _blockgroups_gdf(con)

    parcels = con.execute(
        "SELECT parcel_id, centroid_lon AS lon, centroid_lat AS lat FROM raw_parcels "
        "WHERE centroid_lon IS NOT NULL AND centroid_lat IS NOT NULL"
    ).fetchdf()
    parcel_points = gpd.GeoDataFrame(
        parcels, geometry=gpd.points_from_xy(parcels["lon"], parcels["lat"]), crs="EPSG:4326"
    )

    joined = gpd.sjoin(parcel_points, blockgroups, how="left", predicate="intersects")
    # A centroid sitting exactly on a shared border can match more than one
    # polygon; keep one deterministic match per parcel.
    result = (
        joined[["parcel_id", "bg_geoid", "lon", "lat"]]
        .sort_values("bg_geoid", na_position="last")
        .drop_duplicates("parcel_id")
        .reset_index(drop=True)
    )

    con.register("_parcel_geo_tmp", result)
    try:
        con.execute("CREATE OR REPLACE TABLE parcel_geo AS SELECT * FROM _parcel_geo_tmp")
    finally:
        con.unregister("_parcel_geo_tmp")

    matched = int(result["bg_geoid"].notna().sum())
    print(
        f"parcel_geo: {len(result)} parcels, {matched} matched to a block group "
        f"({len(result) - matched} outside every polygon)"
    )
    return result


def blockgroup_centroids(con: duckdb.DuckDBPyConnection, crs: str = "EPSG:32617") -> gpd.GeoDataFrame:
    """Block-group centroids in a metric CRS — UTM zone 17N by default,
    which is exact (not just approximate, unlike Web Mercator) for Detroit's
    location. Used by features.py for the corridor-distance feature."""
    gdf = _blockgroups_gdf(con).to_crs(crs)
    return gpd.GeoDataFrame({"bg_geoid": gdf["bg_geoid"]}, geometry=gdf.geometry.centroid, crs=crs)


def export_blockgroups_geojson(con: duckdb.DuckDBPyConnection, settings: Settings | None = None) -> dict:
    """Simplified block-group polygons for the frontend map, cached to
    data/blockgroups.geojson."""
    settings = settings or get_settings()
    blockgroups = _blockgroups_gdf(con)
    blockgroups["geometry"] = blockgroups["geometry"].simplify(
        SIMPLIFY_TOLERANCE_DEG, preserve_topology=True
    )
    geojson: dict = json.loads(blockgroups.to_json())

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    out_path = settings.data_dir / "blockgroups.geojson"
    out_path.write_text(json.dumps(geojson))
    print(f"wrote {len(blockgroups)} block-group polygons -> {out_path}")
    return geojson
