"""Parcel centroid -> block-group GEOID spatial join.

Contract (md/architecture.md §6):
    assign_block_groups(con) -> None            # writes parcel_geo
    export_blockgroups_geojson(con) -> dict      # simplified polygons for the map

Build order milestone: step 3 (Geo + features). Not yet implemented.
"""
from __future__ import annotations

import duckdb


def assign_block_groups(con: duckdb.DuckDBPyConnection) -> None:
    """geopandas.sjoin of parcel centroids (raw_parcels geometry) against
    raw_blockgroups polygons; writes one row per parcel to parcel_geo."""
    raise NotImplementedError("geo.assign_block_groups: see md/architecture.md §6")


def export_blockgroups_geojson(con: duckdb.DuckDBPyConnection) -> dict:
    """Simplified block-group polygons for the frontend map, cached to
    data/blockgroups.geojson."""
    raise NotImplementedError("geo.export_blockgroups_geojson: see md/architecture.md §6")
