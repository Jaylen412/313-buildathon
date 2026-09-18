"""Detroit Open Data ArcGIS REST layer definitions.

Endpoints, row counts, and field lists verified live on 2026-09-18 — see
md/architecture.md §1 for the full notes and gotchas (trailing periods on
parcel_id, junk sale rows, the permit-aggregate decoy layer to avoid, etc).
All layers cap at 1,000 records/response; ingest.py paginates with
resultOffset.
"""
from __future__ import annotations

from dataclasses import dataclass

ARCGIS_ROOT = "https://services2.arcgis.com/qvkbeam7Wirps6zC/ArcGIS/rest/services"


@dataclass(frozen=True)
class Layer:
    name: str
    """Internal table name -> raw_{name}."""
    service: str
    """ArcGIS service name, layer 0 unless noted."""
    out_fields: list[str]
    date_field: str | None = None
    """Field used for --since incremental pulls, if any."""
    return_geometry: bool = False
    """Full polygon geometry, stored as an Esri-JSON string in a `geometry`
    column (parsed by geo.py, not ingest.py). Use for BLOCKGROUPS only —
    378k parcel polygons would be far too slow to page through."""
    return_centroid: bool = False
    """Lightweight point centroid only (returnCentroid=true), stored as
    centroid_lon/centroid_lat float columns. Use for PARCELS."""
    layer_id: int = 0

    @property
    def layer_url(self) -> str:
        """Layer metadata endpoint (`?f=json` reports objectIdField etc)."""
        return f"{ARCGIS_ROOT}/{self.service}/FeatureServer/{self.layer_id}"

    @property
    def query_url(self) -> str:
        return f"{self.layer_url}/query"


PARCELS = Layer(
    name="parcels",
    service="parcel_file_current",
    return_centroid=True,
    out_fields=[
        "parcel_id", "address", "zip_code", "taxpayer_1", "taxpayer_2",
        "taxpayer_address", "taxpayer_city", "taxpayer_state", "taxpayer_zip_code",
        "property_class", "property_class_description", "use_code", "zoning_district",
        "tax_status", "amt_assessed_value", "amt_assessed_value_previous",
        "amt_taxable_value", "amt_taxable_value_previous", "amt_land_value",
        "pct_pre_claimed", "nez_district", "is_improved", "sale_date", "amt_sale_price",
        "total_square_footage", "total_floor_area", "total_acreage", "year_built",
        "census_tract_geoid_2020", "neighborhood", "council_district", "ward",
    ],
)

SALES = Layer(
    name="sales",
    service="assessor_property_sales_view",
    date_field="sale_date",
    out_fields=[
        "sale_id", "parcel_id", "address", "sale_date", "amt_sale_price",
        "grantor", "grantee", "liber_page", "term_of_sale", "sale_verification",
        "sale_instrument", "is_multi_parcel_sale", "pct_property_transferred",
        "property_class_code", "property_class_description", "neighborhood",
        "council_district", "zip_code", "longitude", "latitude",
    ],
)

PERMITS = Layer(
    name="permits",
    service="bseed_building_permits",
    date_field="issued_date",
    out_fields=[
        "record_id", "parcel_id", "address", "submitted_date", "issued_date",
        "work_description", "permit_type", "construction_type", "proposed_use_type",
        "use_group", "num_units", "amt_estimated_contractor_cost", "is_vacant",
        "neighborhood", "council_district", "zip_code", "longitude", "latitude",
    ],
)

BLIGHT = Layer(
    name="blight",
    service="blight_tickets",
    date_field="ticket_issued_date",
    out_fields=[
        "ticket_id", "ticket_number", "parcel_id", "address", "ordinance_law",
        "ordinance_description", "disposition", "ticket_issued_date", "judgment_date",
        "payment_date", "amt_fine", "amt_judgment", "amt_payment", "amt_balance_due",
        "payment_status", "collection_status", "property_owner_name",
        "property_owner_state", "neighborhood", "council_district",
        "longitude", "latitude",
    ],
)

BLOCKGROUPS = Layer(
    name="blockgroups",
    service="CensusBlockgroup2020",
    return_geometry=True,
    out_fields=["GEOID", "TRACTCE", "BLKGRPCE", "ALAND", "INTPTLAT", "INTPTLON"],
)

ALL_LAYERS: list[Layer] = [PARCELS, SALES, PERMITS, BLIGHT, BLOCKGROUPS]

# Known decoy: services6.arcgis.com/ONZht79c8QWuX759/.../Building_Permits is a
# quarterly aggregate table (no parcel_id, no per-record dates). Do not use it.
