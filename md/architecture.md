# Signals — Architecture

Source of truth for module boundaries, data model, and build order. `signal-details.md` is the pitch/spec; this file is what the code follows. `TODO.md` lists the manual tasks that gate each phase.

## 1. Verified data sources (checked 2026-09-18)

All layers live under `https://services2.arcgis.com/qvkbeam7Wirps6zC/ArcGIS/rest/services/`. Every layer caps at 1,000 records per response. Paginate by keyset on the object-id field, not `resultOffset` (see gotchas below).

| Layer | Path | Rows | Geometry | Fields we use |
|---|---|---|---|---|
| Parcels (current) | `parcel_file_current/FeatureServer/0` | 377,940 | polygon | `parcel_id`, `address`, `taxpayer_1`, `taxpayer_2`, `taxpayer_address`, `taxpayer_city`, `taxpayer_state`, `taxpayer_zip_code`, `property_class`, `property_class_description`, `tax_status`, `amt_assessed_value`, `amt_assessed_value_previous`, `amt_taxable_value`, `amt_taxable_value_previous`, `amt_land_value`, `pct_pre_claimed`, `nez_district`, `is_improved`, `sale_date`, `amt_sale_price`, `total_square_footage`, `total_floor_area`, `year_built`, `census_tract_geoid_2020`, `neighborhood`, `council_district`, `zip_code` |
| Property sales (history) | `assessor_property_sales_view/FeatureServer/0` | 537,595 | point | `sale_id`, `parcel_id`, `sale_date` (2011 → present), `amt_sale_price`, `grantor`, `grantee`, `term_of_sale`, `sale_verification`, `sale_instrument`, `is_multi_parcel_sale`, `pct_property_transferred`, `property_class_code`, `longitude`, `latitude` |
| Building permits | `bseed_building_permits/FeatureServer/0` | 47,154 | point | `record_id`, `parcel_id`, `issued_date` (2019 → present), `permit_type`, `work_description`, `construction_type`, `proposed_use_type`, `num_units`, `amt_estimated_contractor_cost`, `is_vacant`, `longitude`, `latitude` |
| Blight tickets | `blight_tickets/FeatureServer/0` | 904,905 | point | `ticket_id`, `parcel_id`, `ticket_issued_date`, `ordinance_description`, `disposition`, `payment_status`, `collection_status`, `amt_fine`, `amt_balance_due`, `property_owner_name`, `property_owner_state`, `longitude`, `latitude` |
| Census block groups 2020 | `CensusBlockgroup2020/FeatureServer/0` | 625 | polygon | `GEOID` (12-digit), `TRACTCE`, `BLKGRPCE`, `ALAND` |
| Census blocks 2020 | `CensusBlocks2020/FeatureServer/0` | — | polygon | not used in v1 |

Gotchas confirmed against the live endpoints:

- **Do not use** `services6.arcgis.com/ONZht79c8QWuX759/.../Building_Permits`. Search surfaces it first, but it is a quarterly aggregate table with no parcel or date columns.
- `parcel_id` carries a trailing period in every layer (`21013863.`). Strip it once in ingest.
- **`resultOffset` pagination is a trap on these layers.** Measured live: the sales view answers offset 0 in 0.5 s, offset 300k in 19 s (42 s with `orderByFields`), and intermittently times out server-side with a generic `400 Invalid query parameters` — which is exactly how the first full ingest run died. Keyset pagination (`WHERE oid > last_seen ORDER BY oid ASC`, `resultRecordCount=1000`) returns the same page in 0.1–0.7 s at any depth on every layer. The object-id field name is not uniform (`ObjectId` on parcels/sales/permits, `OBJECTID` on blight/block groups); `ingest.py` reads `objectIdField` from each layer's metadata rather than hardcoding it.
- Sales history has junk: `$0`/low-dollar transfers and typo dates (years 2202, 2206, 2925 exist). Filter on `amt_sale_price > 1000` and `sale_date` between 2011-01-01 and today. `term_of_sale` is a controlled vocabulary (queried live 2026-09-18); exactly two of ~15 categories are genuinely arm's-length — `03-ARM'S LENGTH` (100,712 of 537,595 rows) and `19-MULTI PARCEL ARM'S LENGTH` (12,116 rows). Everything else (`13-GOVERNMENT`, `10-FORECLOSURE`, `09-FAMILY/RELATED ENTITY`, `21-NOT USED/OTHER`, etc.) is excluded. Match on the `ARM'S LENGTH` substring rather than hardcoding the leading number, in case the assessor renumbers the codes. Do **not** additionally filter on `is_multi_parcel_sale` — the multi-parcel arm's-length category is legitimate and should stay in.
- Parcels carry a tract GEOID but no block-group GEOID. We do a local point-in-polygon join (parcel centroid → block-group polygon).
- Permits start 2019-01-02. Feature-years that include permit signals are limited to 2019+; sales-only features go back to 2011.
- Tax delinquency is Wayne County Treasurer data and is not in any layer above. v1 proxy: unpaid blight balance + parcel `tax_status`. See TODO D.3.
- `pct_pre_claimed` (Principal Residence Exemption) is the exemption signal. HOPE / PAYS enrollment is not in the parcel file.
- **Every layer is Detroit-only at the source, confirmed live** — these are the City of Detroit's own published datasets (parcels from its Assessor, permits from BSEED, blight tickets from its own ticketing system), not a broader region filtered down. The block-group layer's 625 rows confirms this: Wayne County alone has roughly 1,200 block groups and Michigan has about 8,200, so 625 lines up with Detroit specifically. No extra geographic filter is applied in `ingest.py` because none is needed.
- **Blight tickets (904,905 rows) is the largest layer** — nearly double sales and permits combined, and bigger than originally estimated. It dominates the ingest request count: ~1,870 paginated requests across all five layers. With keyset pagination each page is well under a second, so the whole pull should land around 10–15 minutes.
- **Real-data shape after the first full run (2026-09-18):** `sales_clean` = 110,097 arm's-length sales; 2011–2012 are thin (~900–1,000 sales/yr city-wide), 2013+ run 4.5k–9.6k/yr, and from 2014 on 470–550 of the 625 block groups have ≥3 sales a year (so `price_yoy` is defined for ~400–530 block groups per year). Permits and `dist_to_hot_corridor_m` exist from 2019/2020 respectively. **2026 is a partial year** (through mid-September) — the forecast must not use it as a target year. Blight has 56 rows dated 2027–8535 and 8 before 2000; `features.py` bounds both permit and blight aggregates to `[2011, current year]`.
- **What the forecast actually finds hot (trained model, 2025 features):** the ring around the already-hot core — Hubbard Richard (next to Corktown/Mexicantown), McDougall-Hunt and Poletown East (beside Eastern Market/Brush Park), Riverbend (by Jefferson-Chalmers), Dexter-Linwood, Nardin Park. Typical signals: LLC share above the city, a one-year price dip in a thin market, close to a high-permit corridor. 191 of 625 block groups score ≥ 70; 76 are low-confidence (< 3 sales in 2025), 3 of those ≥ 70. The trained model and the *original* momentum-positive index were rank-correlated −0.33; that disagreement is what exposed the sign error.
- All pulled data lives entirely on the local machine: `backend/data/raw/*.parquet` (one file per layer) and `backend/data/signals.duckdb`. Nothing is uploaded anywhere; only the read-only queries to the public ArcGIS endpoints leave the machine.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Geographic unit | Census block group (2020), behind a `GEO_LEVEL` constant | Census blocks average 10–30 parcels; yearly sale medians would be empty. Block groups (~300–600 parcels) give a real signal and still look like corridor-scale "blocks" on the map. |
| Store | DuckDB single file `backend/data/signals.duckdb`; raw pulls cached as Parquet in `backend/data/raw/` | Zero setup, fast aggregates, re-runs never re-hit ArcGIS. |
| Spatial join | `geopandas` + `shapely`, run once at ingest, persisted | One-time cost; everything downstream is plain SQL/pandas. |
| Forecast model | `sklearn.ensemble.HistGradientBoostingRegressor` | No compiled deps, handles NaNs, fast on ~1,000 rows × ~10 years. |
| Target | 2-year forward change in log median arm's-length price per sq ft, per block group | Directly "investment pressure"; sales history is deep enough. |
| Heat score | City-wide percentile rank of the predicted growth, 0–100 | Interpretable and stable across model versions. |
| Top signals per block | Block's feature z-scores × global permutation importance, top 3 | Deterministic and defensible out loud; no SHAP dependency. |
| Forecast inputs | Momentum, LLC share, permits, blight, corridor distance, sale count. **Not** price levels (`median_ppsf`, `median_price`) and **not** snapshot columns | Levels made the first real model rank the cheapest $8–22/sqft block groups hottest (pure mean reversion); snapshots leak the present into the backtest. See §6. |
| Fallback | Weighted z-score index with the weights table printed in the backtest report, **sign-checked on real data** | Required by the spec when training data is thin or backtest is poor. The first draft weighted one-year price momentum positively and was anti-predictive on every holdout year; momentum is now discounted. Selected by config, labelled in the UI. |
| Python toolchain | `uv` + `pyproject.toml`, Python 3.12 | Fast installs, lockfile. |
| Frontend | Vite + React + TypeScript, `react-leaflet`, TanStack Query, plain CSS | Two screens; no design system needed. |
| Basemap | Esri World Light Gray Base raster tiles | No API key. CARTO Positron was the first choice but now watermarks tiles "API KEY REQUIRED" without a key (seen live 2026-09-18). |
| LLM call | OpenAI Python SDK, Responses API with Structured Outputs (`strict: true` JSON schema generated from the `Brief` Pydantic model); model from `OPENAI_MODEL` env var | User has existing OpenAI credits. Schema-enforced output; model is swappable without code changes. |
| Household gating | `X-Org-Token` header must equal `SIGNALS_ORG_TOKEN`; `SIGNALS_DEMO=1` anonymizes | Spec's non-negotiable: only block-level is public. The token is a single shared secret standing in for "organization accounts"; real login is out of scope for the hackathon. |

## 3. Repo layout

```
313-buildathon/
├── backend/
│   ├── pyproject.toml            # uv; fastapi, uvicorn, duckdb, pandas, pyarrow, geopandas, shapely,
│   │                             # scikit-learn, httpx, pydantic-settings, openai, typer, pytest
│   ├── .env.example
│   ├── signals/
│   │   ├── config.py             # Settings from env: OPENAI_API_KEY, OPENAI_MODEL, CENSUS_API_KEY, SIGNALS_ORG_TOKEN,
│   │   │                         # SIGNALS_DEMO, GEO_LEVEL, DATA_DIR, MODEL_MODE (trained|fallback|auto)
│   │   ├── db.py                 # DuckDB connection + schema DDL
│   │   ├── sources.py            # layer URLs + outFields lists (section 1)
│   │   ├── ingest.py             # ArcGIS paginator → parquet → raw_* tables
│   │   ├── geo.py                # parcel centroid → block-group GEOID; block-group GeoJSON export
│   │   ├── features.py           # bg_features (block group × year)
│   │   ├── forecast.py           # train / backtest / score; fallback index
│   │   ├── vulnerability.py      # owner-occupied parcel ranking on hot block groups
│   │   ├── brief.py              # LLM outreach brief (OpenAI), schema-constrained
│   │   ├── demo.py               # demo corridor GEOIDs + anonymization helpers
│   │   ├── store.py              # read-side queries for the API (map payload, detail, trend)
│   │   ├── api.py                # FastAPI app
│   │   └── cli.py                # `signals ingest|features|train|score|serve`
│   ├── tests/
│   └── data/                     # gitignored: raw/*.parquet, signals.duckdb, models/
├── frontend/
│   ├── package.json, vite.config.ts, index.html
│   └── src/
│       ├── api.ts                        # typed fetchers + ApiError (surfaces FastAPI `detail`)
│       ├── heat.ts                       # single-hue sequential ramp for the heat score
│       ├── App.tsx                       # map + drawer layout
│       └── components/
│           ├── HeatMap.tsx               # react-leaflet choropleth of block groups
│           ├── BlockDrawer.tsx           # score, top signals, trend, households
│           ├── Trend.tsx                 # single-series sparklines (small multiples)
│           ├── HouseholdList.tsx         # ranked rows, reason chips, heirship as "follow-up flag"
│           └── BriefPanel.tsx            # "Generate brief" → rendered sections
├── md/
│   ├── signal-details.md         # pitch/spec
│   ├── architecture.md           # this file
│   └── TODO.md                   # manual tasks
├── CLAUDE.md
└── README.md
```

## 4. Pipeline

```
ArcGIS REST ──ingest.py──▶ raw_parcels / raw_sales / raw_permits / raw_blight / raw_blockgroups
                                │
                             geo.py ──▶ parcel_geo (parcel_id → bg_geoid, lon, lat)
                                │
                          features.py ──▶ sales_clean, bg_features (bg_geoid × year)
                                │
                          forecast.py ──▶ bg_scores (+ models/backtest_report.json)
                                │
                       vulnerability.py ──▶ parcel_vulnerability (hot block groups only)
                                │
                             api.py ──▶ /api/blocks, /api/blocks/{geoid}, /households, /brief
                                │                                             │
                          frontend map/drawer                            brief.py → OpenAI
```

Each stage reads only the previous stage's tables. Re-running any stage overwrites its own outputs and nothing upstream.

## 5. Data model (DuckDB)

**Raw** (as pulled, `parcel_id` normalized): `raw_parcels` (centroid_lon/lat instead of full polygons — see §1), `raw_sales`, `raw_permits`, `raw_blight`, `raw_blockgroups` (GEOID + `geometry_json`, the raw Esri-JSON polygon string; `geo.py` parses it, ingest.py does not).

**`parcel_geo`** `(parcel_id PK, bg_geoid, lon, lat)` — output of `geo.py`.

**`sales_clean`** — `raw_sales` filtered to arm's-length (`term_of_sale` matches `ARM'S LENGTH`, see §1), `amt_sale_price > 1000`, `sale_date` in `[2011-01-01, today]`, plus:
- `is_llc_buyer`: grantee matches `\b(LLC|L\.L\.C|INC|CORP|TRUST|HOLDINGS|PROPERTIES|INVEST\w*|VENTURES|GROUP)\b`
- `is_out_of_state_buyer`: current parcel `taxpayer_state != 'MI'` (snapshot; noted as such)
- `ppsf`: `amt_sale_price / total_floor_area` where floor area > 200

**`bg_features`** `(bg_geoid, year, ...)`, one row per block group per year 2011–current:

| Column | Definition |
|---|---|
| `n_sales` | arm's-length sales that year |
| `median_price`, `median_ppsf` | medians over those sales |
| `price_yoy` | log change in `median_ppsf` vs prior year (NaN if either side < 3 sales) |
| `llc_share`, `out_of_state_share` | share of that year's sales |
| `permit_count`, `permit_value` | permits issued that year, sum of `amt_estimated_contractor_cost` |
| `new_construction_permits` | `permit_type` / `work_description` matching new build |
| `permit_count_yoy` | log change vs prior year |
| `blight_tickets` | tickets issued that year |
| `vacant_share` | parcels with `is_improved = 0` or vacant-land property class (snapshot) |
| `owner_occ_share` | parcels with `pct_pre_claimed > 0` (snapshot) |
| `dist_to_hot_corridor_m` | distance (meters, UTM zone 17N — exact for Detroit) from block-group centroid to nearest of the top-25 block groups by `permit_value` in the prior year; NaN before there's a prior year with permit data (i.e. before 2020) |

**`bg_scores`** `(bg_geoid PK, heat_score INT, predicted_growth DOUBLE, confidence 'ok'|'low', top_signals JSON, model_version, model_mode, scored_at TIMESTAMPTZ)`.

**`parcel_vulnerability`** `(parcel_id PK, bg_geoid, rank, score, reasons JSON, heirship_flag BOOL, computed_at)`.

**Briefs** are cached as JSON files, `data/briefs/{geoid}.{model_version}.{llm_model}.json`, each holding the `BlockSummary` sent and the `Brief` returned. (Not a DuckDB table: the API's connection is read-only, and a file cache survives re-ingests.)

## 6. Module contracts

### `ingest.py`
- `pull_layer(layer, since=None) -> Path` — keyset-paginates on the layer's `objectIdField` (read from metadata) with `resultRecordCount=1000`, `returnCentroid=true` for parcels, full `returnGeometry` only for block groups, retries with backoff, writes `data/raw/{name}.parquet`.
- `load_all(con, since=None, resume=False)` — parquet → `raw_*` tables, normalizes `parcel_id`. `resume=True` (CLI `--resume`) skips the network pull for layers whose parquet already exists, so a crashed run continues instead of re-pulling finished layers.
- Idempotent. `--since` supported for permits, sales, blight.

### `geo.py`
- `assign_block_groups(con)` — parcel centroids (from `returnCentroid`) → `parcel_geo` via `geopandas.sjoin`.
- `export_blockgroups_geojson(con) -> dict` — simplified polygons for the map, cached to `data/blockgroups.geojson`.

### `features.py`
- `build_features(con) -> pd.DataFrame` — writes `sales_clean` and `bg_features`. Pure SQL/pandas.

### `forecast.py`
- `train(features) -> tuple[Model, dict]` — rows: `(bg_geoid, year T)` with target `median_ppsf[T+2] − median_ppsf[T]` in log space, T ≤ current − 2. Hold out the latest available window as backtest. Report MAE, R², Spearman ρ, feature importances, training row count to `data/models/backtest_report.json`.
- `score(model, features) -> pd.DataFrame` — predicts on latest year, percentile-ranks to `heat_score`, computes `top_signals` (top 3 `[{feature, value, z, direction}]`).
- `fallback_index(features) -> pd.DataFrame` — published weights: `llc_share 0.35, price_yoy −0.25, permit_count_yoy 0.15, permit_value 0.10, dist_to_hot_corridor_m −0.15`; same output shape, `model_mode='fallback'`. The report carries this index's own Spearman on each of the last five holdout years next to the model's.
- Training rows require ≥ 5 sales at both ends of the window and a starting `median_ppsf ≥ $20` (log ratios of near-zero land sales are noise). Every score carries `confidence` = `low` when the block group had < 3 sales in the scoring year.
- `MODEL_MODE=auto` picks fallback when training rows < 500 or backtest Spearman ρ < 0.2.
- `SIGNAL_LABELS` maps each feature to plain language for the drawer and the brief.
- **Real-data backtest (2026-09-18, holdout 2023, 2,626 training rows):** MAE 0.215 vs 0.229 predict-the-mean, R² 0.10, Spearman 0.39 (0.31 on a 2022 holdout). Top importances: `price_yoy`, `llc_share`, `dist_to_hot_corridor_m`. The skill is real but modest, and the single strongest effect is *reversal*: one-year price momentum alone scores Spearman −0.35 to −0.40 against realized two-year growth. Without `price_yoy` the model has no skill (≈0.0); with a smoother two-year momentum it keeps most of it (0.24–0.29). The chosen fallback index scores +0.13 to +0.32 across 2019–2023; a two-term `llc_share + reversal` index scores +0.24 to +0.36 but drops the permit and corridor signals the product names. Index candidates were compared on the same five years, so treat the weight choice as backtested, not tuned.

### `vulnerability.py`
- `rank(con, bg_geoid, hot_threshold=70) -> list[Household]` — only for block groups with `heat_score ≥ hot_threshold`.
- Owner-occupied: `pct_pre_claimed > 0` OR normalized `taxpayer_address == address`; residential property class only.
- Score terms (weight, reason string):
  - Missing PRE while apparently owner-occupied (3.0) — "No Principal Residence Exemption on file"
  - Unpaid blight balance > 0 (2.0) — "Unpaid blight ticket balance (delinquency proxy)"
  - Tenure: years since last arm's-length sale, capped at 30, ×0.1 (max 3.0) — "Owned N+ years"
  - Uncapping exposure: `(amt_assessed_value − amt_taxable_value) / amt_assessed_value` ×2.0 — "Taxable value far below assessed; a transfer would spike the bill"
  - Heirship flag (1.0, boolean) — "Possible heirs' property: follow up, not a determination". Triggers on `taxpayer_1` containing `ESTATE OF|HEIRS|ET AL|DECEASED|C/O`, or taxpayer surname ≠ last grantee surname with last sale > 15 years ago.
- Output is anonymized by `demo.py` when `SIGNALS_DEMO=1`: names dropped, address → hundred-block, no `parcel_id`.
- **As built against the real parcel file (2026-09-18):** residential = `property_class IN ('401','407')`; owner-occupied = `pct_pre_claimed > 0` OR (address key = house number + first street token matches, since mailing addresses differ mostly by suffix) AND the taxpayer isn't an entity (LLC/INC/TRUST/LAND BANK/…; some LLCs list the property as their own mailing address). Tenure = years since the last arm's-length sale since 2011, else the parcel file's own `sale_date` (text, cast on read; covers 202k of 213k residential parcels), else unknown → cap points + "No sale on record". The taxable/assessed gap has a median of 0.61 among PRE homes (Michigan's cap), so its reason line only appears at ≥ 0.5. Blight balance is the delinquency proxy (89,880 parcels, $135M outstanding). `Household` also carries `owner`, `tenure_years`, `has_pre`, `unpaid_blight_balance`, `uncapping_gap`. Real output: 86 households on the top block group (40 missing PRE, 23 with a blight balance, 1 heirship flag), 167 on Hubbard Richard.

### `brief.py`
- `generate_brief(summary: BlockSummary) -> Brief`
- `BlockSummary`: `bg_geoid`, `neighborhood`, `heat_score`, `top_signals`, 5-year `trend` arrays, `n_owner_occupied`, `n_flagged_households`, aggregate reason counts (no household rows).
- `Brief` schema: `headline`, `what_is_changing: list[str]`, `why_it_matters: str`, `protections_to_offer: list[{name, who_qualifies, first_step}]`, `canvassing_plan: list[str]`, `caveats: list[str]`.
- Provider: OpenAI Responses API via `client.responses.parse(model, instructions, input, text_format=Brief)`, which derives the strict JSON schema from the Pydantic model and returns `output_parsed`. Model name comes from `OPENAI_MODEL` so it can be changed without a code edit. `_enforce_protections` drops any name not on the vetted list after parsing.
- `build_block_summary(con, geoid, report)` assembles the summary from `store.block_detail` + `vulnerability.rank(persist=False)`: only counts of reason types reach the model (`missing_pre`, `unpaid_blight_balance`, `long_tenure`, `no_sale_on_record`, `uncapping_exposure`, `possible_heirs_property`). The partial current year is excluded from the trend.
- `get_or_create_brief(...) -> (Brief, cached, summary)`; `force=True` regenerates. `signals brief <geoid…>` is the CLI front for pre-caching.
- System prompt: explain, never compute; only cite numbers present in the summary; protections limited to the vetted list in `config.PROTECTIONS` (see TODO D.2).

### `api.py`
| Route | Returns | Gate |
|---|---|---|
| `GET /api/health` | ok, configured/scored model mode, scored_at, n_scored, demo flag | — |
| `GET /api/demo/corridors` | the fly-to presets from `demo.DEMO_CORRIDORS`, each with live `neighborhood`, `heat_score`, `confidence`; `suggested` marks data-driven placeholders the user hasn't confirmed | public |
| `GET /api/blocks` | GeoJSON FeatureCollection: `bg_geoid`, `neighborhood`, `heat_score`, `confidence`, `top_signals` (with `label`), `model_mode`. Built from the cached `blockgroups.geojson` + `bg_scores`, cached in-process keyed on `scored_at`; 503 until `signals train` has run | public |
| `GET /api/blocks/{geoid}` | the score row + `neighborhood` (most common parcel neighborhood), `trend` (`years`, per-metric `series`, `partial_year`), `backtest_summary` footnote (backtest numbers, or "weighted index" in fallback mode); 404 for an unknown GEOID | public |
| `GET /api/blocks/{geoid}/households` | `{hot, hot_threshold, anonymized, heirship_note, households[]}` — computed live via `vulnerability.rank(persist=False)`; `hot=false` with an empty list below the threshold; 404 for an unknown GEOID | `X-Org-Token`; anonymized in demo |
| `POST /api/blocks/{geoid}/brief` (+`?force=true`) | `{bg_geoid, neighborhood, cached, llm_model, brief}`; 503 if the key is missing, 502 with the provider's message if the call fails, 404 for an unknown GEOID | `X-Org-Token` |

The API opens a **read-only DuckDB connection per request** (thread-safe, always sees the latest `signals train`). DuckDB cannot serve reads while another process holds the file for writing, so run pipeline commands with the API stopped.

**Org token.** `SIGNALS_ORG_TOKEN` is one long random string in `backend/.env`. The frontend reads the same value from `VITE_ORG_TOKEN` in `frontend/.env.local` and sends it as the `X-Org-Token` header on the two gated routes. A matching header means "CDO staff"; anything else gets block-level data only. There is no login UI in v1.

## 7. Build order

Core path first, matching the spec cut-line. Each milestone is demoable on its own.

1. **Scaffold** — `uv init` backend, `npm create vite` frontend, `.env.example`, `.gitignore` additions (`backend/data/`, `.env`, `.venv/`, `node_modules/`, `dist/`), CLAUDE.md commands.
2. **Ingest** — paginator + five layers → parquet → DuckDB. Check: row counts within 1% of live counts.
3. **Geo + features** — centroid join; `bg_features` 2011–current. Check: chosen demo corridor shows rising `permit_value` and `llc_share`.
4. **Forecast** — train, backtest, report, fallback switch, score all block groups.
5. **API + map** — choropleth, click → drawer with score and top signals. *Milestone 1.*
6. **Vulnerability** — ranking, gated + anonymized endpoint, `HouseholdList`. *Milestone 2.*
7. **Brief** — `brief.py` + `BriefPanel`. *Milestone 3 = full demo.*
8. **Polish** — corridor fly-to presets from `demo.py` (done: `CorridorBar`), loading states (done: drawer skeleton, offline / not-scored banners), README run steps (done).

Stretch, only after 7: Census ACS join, land value tax simulator.

## 8. Verification

- `uv run pytest`: paginator (mocked HTTP), sales filters, feature aggregation on a synthetic block group, fallback determinism, vulnerability reasons, brief schema round-trip.
- `uv run signals ingest && uv run signals features && uv run signals train && uv run signals score` completes and prints row counts.
- `uv run signals serve` + `npm run dev`: click a demo-corridor block group → drawer shows score and 3 signals; households load with the token; brief returns schema-valid JSON in under 15 s.
- `SIGNALS_DEMO=1`: no names, hundred-block addresses only.
- Drawer footer shows either "model v1 · backtest ρ = …" or "weighted index (fallback)".
