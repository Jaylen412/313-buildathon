"""Block-group x year feature aggregation.

Contract (md/architecture.md §5-6):
    build_features(con) -> pd.DataFrame   # writes sales_clean + bg_features

Build order milestone: step 3 (Geo + features). Not yet implemented.
"""
from __future__ import annotations

import duckdb
import pandas as pd


def build_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Filter raw_sales to arm's-length sales (sales_clean), then aggregate
    parcel_geo + sales_clean + raw_permits + raw_blight to bg_features
    (one row per bg_geoid x year, 2011-current). See §5 for the column list."""
    raise NotImplementedError("features.build_features: see md/architecture.md §5-6")
