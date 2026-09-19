# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Scaffolding, `ingest.py` (step 2), and `geo.py` + `features.py` (step 3) are all implemented. `ingest.py` is an ArcGIS REST paginator with retry/backoff, incremental `--since` refresh, and `parcel_id` normalization, verified live against all five endpoints; its arm's-length sales filter (`term_of_sale` matches `ARM'S LENGTH`) is grounded in a live query of the real category breakdown, not a guess (see `md/architecture.md` §1). `geo.py` parses the raw Esri-JSON block-group polygons and does the parcel-centroid spatial join; `features.py` builds `sales_clean` and the `bg_features` block-group×year table, including year-over-year deltas and a UTM-metric corridor-distance feature. Both are verified against the real pull (2026-09-18): `backend/data/` holds all five layers (~295 MB, gitignored) and `bg_features` is 625 block groups × 16 years (2011–2026) with the expected Detroit hot spots on top. `forecast.py` (step 4) is implemented and run: `bg_scores` holds 625 scored block groups from the trained model (holdout Spearman 0.39; see `md/architecture.md` §6 for why price-level features are excluded and why the fallback index discounts one-year momentum — both were real-data findings, don't reintroduce them). Step 5 (API + map) is done and is demo milestone 1: `signals/store.py` holds the read-side queries, `api.py` serves `/api/blocks` (GeoJSON + scores, cached on `scored_at`) and `/api/blocks/{geoid}` (signals with `SIGNAL_LABELS`, trend series, backtest footnote) over a read-only DuckDB connection per request; the frontend draws the choropleth (`src/heat.ts` is the single-hue ramp; basemap is Esri's keyless light-gray canvas — CARTO now requires a key) and the drawer: households first, trend charts collapsed below. Restart the API with `pkill -f "signals serve"` — the process name is `signals serve`, not `signals.api:app`, and a stale server on port 8000 will silently keep answering old routes. Step 6 (vulnerability) is done: `vulnerability.py` ranks owner-occupied parcels on hot block groups with a reason per term, `demo.py` anonymizes for `SIGNALS_DEMO=1`, and the households route computes it live on the read-only connection (`persist=False`). Rules were fitted to the real parcel file — see the module docstring before changing them (401/407 classes, number+street address matching, entities excluded, NULL text arrives as NaN). Step 7 (brief) is done: `brief.py` builds an aggregate-only `BlockSummary`, calls OpenAI `responses.parse` with `text_format=Brief` (strict schema), enforces `config.PROTECTIONS` after the fact, and caches JSON under `data/briefs/` (file cache, not DuckDB — the API connection is read-only). `uv run signals brief <geoid…>` pre-generates for offline demos. All eight build steps are complete (step 8 added `/api/demo/corridors`, the preset bar, offline/not-scored banners, and README run instructions). Step 9 added the **Neighborhoods page**: `store.py` rolls the 625 block groups up into the 186 named neighborhoods they share (majority-vote parcel `neighborhood`), `/api/neighborhoods` + `/api/neighborhoods/{slug}` serve the ranked list and an aggregated `Trend`-shaped series, and `explain.py` + gated `POST /api/neighborhoods/{slug}/summary` turn those metrics into **one paragraph** of plain prose (the schema is a single `summary` string — the page already shows the figures, so the paragraph says what they add up to). Two real-data findings there are load-bearing: aggregated signal directions must support `mixed` (Bethune Community's `price_yoy` is 5 block groups down, 4 up — a majority-wins rule published "below the city in 9 of 9", which was true of none of them), and a mean of cross-sectional z-scores is not a z-score for the neighborhood, so `mean_z` is only ever rendered as "in k of n block groups". Neighborhood medians are recomputed from `sales_clean`, never averaged from block-group medians. Remaining work is the user's TODO items and the deployment decision (Vercel can't host the DuckDB backend; see the architecture notes if asked to build a static export). 2026 is a partial year: the forecast never uses it as a target and scores on 2025 features. Runtime gotcha: DuckDB needs `pytz` to return the tz-aware `scored_at` column (pandas 3 dropped it); it's a declared dependency now. It is the workspace for **Signals**, a 313 Buildathon project. `README.md` is the public pitch; `md/signal-details.md` is the working spec (pitch, cut-line, demo script, risks); `md/architecture.md` is the source of truth for data sources, decisions, module contracts, data model, and build order; `md/TODO.md` tracks the manual tasks the user must do (keys, data pulls, local-knowledge decisions). Read `md/architecture.md` before implementing anything — the build order (§7) is complete.

Follow the repo layout and module contracts already established in `backend/signals/` and `frontend/src/` (which mirror `md/architecture.md` §3 and §6) rather than inventing a new structure.

## Commands

Backend (from `backend/`, via `uv`):

```
uv sync                    # install/sync dependencies
uv run pytest -q           # run tests
uv run signals ingest      # pull ArcGIS layers -> data/raw/*.parquet + DuckDB (long-running, ~15-30 min)
uv run signals features    # build sales_clean + bg_features
uv run signals train       # train/fallback + score all block groups
uv run signals brief <geoid…>   # pre-generate + cache outreach briefs (offline demo)
uv run signals explain <slug…>  # pre-generate + cache neighborhood metric summaries
uv run signals serve       # run the API on http://127.0.0.1:8000 (--reload by default)
```

Frontend (from `frontend/`, via `npm`):

```
npm install     # install dependencies
npm run dev     # start Vite dev server
npm run build   # tsc -b && vite build (type-checks + production bundle)
npm run lint    # oxlint
```

Both `backend/.env` (copy from `backend/.env.example`) and `frontend/.env.local` need `OPENAI_API_KEY`/`SIGNALS_ORG_TOKEN` and `VITE_ORG_TOKEN` respectively before the gated routes or `/brief` work — see `md/TODO.md` section A.

## What Signals is

An anti-displacement early-warning tool for Detroit. Two chained models over public data:

1. **Block-level forecast** — predicts investment pressure (12–36 months out) from permit velocity, sale-price trends, LLC/out-of-state buyer share, new construction, corridor proximity. Produces a heat score 0–100.
2. **Parcel-level vulnerability ranking** — on hot blocks only, ranks owner-occupied parcels by missing exemptions, tax delinquency, long tenure, likely heirship/tangled title.

The LLM's role in the product is **interpretation only** (OpenAI, model from `OPENAI_MODEL`). Two endpoints, both schema-constrained and both fed aggregates only: `brief.py` turns a block group's structured summary into a one-page outreach brief, and `explain.py` turns a neighborhood's metrics into a one-paragraph plain-language reading. They explain scores; they never compute them. The explainer is additionally forbidden from naming any protection or program — that is the brief's job, and only the brief's list is vetted.

## Planned architecture

FastAPI backend + React (Vite) frontend, Leaflet map, SQLite/DuckDB local store.

Backend pipeline is a linear chain of modules, each consuming the previous one's output:

- `ingest.py` — Detroit Open Data Portal ArcGIS REST endpoints (Parcels, Building Permits, Blight Violations) → local DB
- `features.py` — aggregate parcel/permit/sales rows to block or block-group level; join Census ACS tenure/income
- `forecast.py` — gradient-boosted model, features at year T predict growth at T+2 → heat score + top contributing features
- `vulnerability.py` — rank owner-occupied parcels on hot blocks
- `/brief` — OpenAI call with a strict output schema
- `/api/neighborhoods/{slug}/summary` — OpenAI call explaining a neighborhood's aggregated metrics (strict schema, no program recommendations)

Frontend screens: the heat map with a block drawer (ranked households + "Generate brief"), and the Neighborhoods page (searchable ranked list → aggregated trend detail + "Summarize these metrics"). Navigation is a `useState<ViewName>` switch in `App.tsx` — there is no router, so nothing is deep-linkable.

## Non-negotiable design constraints

These come from the spec's risk analysis and should survive refactors:

- **Scoring stays deterministic and in code.** Feature engineering, the forecast, and the ranking must be inspectable; every score surfaces its top contributing signals so an organizer can defend it out loud. Do not move scoring logic into an LLM call.
- **Household-level data is gated.** Only block-level scores are safe to expose publicly; per-household rankings sit behind organization accounts. Demo views are anonymized.
- **Heirship is a flag, never a determination.** Name-matching heuristics are noisy — label them as follow-up prompts in both data model and UI copy.
- **If sales history is too thin to train on, fall back to a transparent weighted index** and label it as such rather than shipping an unvalidated model.

## Data source gotchas

- ArcGIS REST queries cap at 1,000 records per response. Paginate by **keyset on the layer's object-id field** (`WHERE oid > last ORDER BY oid`), never `resultOffset`: offset paging degrades to ~20 s/page at depth on the sales view and intermittently fails with a generic 400. The oid field name differs per layer (`ObjectId` vs `OBJECTID`) — `ingest.py` reads it from layer metadata.
- Live endpoint URLs and field names are verified and listed in `md/architecture.md` §1. Sales history is a separate layer (`assessor_property_sales_view`, 2011 → present); permits start 2019. `parcel_id` has a trailing period in every layer. Do not use the `services6…/Building_Permits` aggregate table.
- Census ACS pulls require an API key.
- `OPENAI_API_KEY` is required only for `/brief`; every other stage runs offline from DuckDB.

## Scope discipline

The spec defines an explicit cut-line. **Keep:** block heat score → map → outreach brief. **Drop first, in order:** land value tax simulator, Census join, per-household ranking (falling back to block-level only). Don't build stretch features before that core path runs end to end.
