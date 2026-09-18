# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Scaffolding, `ingest.py` (step 2), and `geo.py` + `features.py` (step 3) are all implemented. `ingest.py` is an ArcGIS REST paginator with retry/backoff, incremental `--since` refresh, and `parcel_id` normalization, verified live against all five endpoints; its arm's-length sales filter (`term_of_sale` matches `ARM'S LENGTH`) is grounded in a live query of the real category breakdown, not a guess (see `md/architecture.md` §1). `geo.py` parses the raw Esri-JSON block-group polygons and does the parcel-centroid spatial join; `features.py` builds `sales_clean` and the `bg_features` block-group×year table, including year-over-year deltas and a UTM-metric corridor-distance feature. Both are covered by unit tests against synthetic geometry (29 tests total) but have not yet run against the real pull. `forecast.py`, `vulnerability.py`, and `brief.py` are still stubs. The user's `uv run signals ingest` (build-order step 2) is running now (see `md/TODO.md` C.1); once it finishes, `uv run signals features` exercises step 3 against real data for the first time. It is the workspace for **Signals**, a 313 Buildathon project. `README.md` is the public pitch; `md/signal-details.md` is the working spec (pitch, cut-line, demo script, risks); `md/architecture.md` is the source of truth for data sources, decisions, module contracts, data model, and build order; `md/TODO.md` tracks the manual tasks the user must do (keys, data pulls, local-knowledge decisions). Read `md/architecture.md` before implementing anything — the current build-order step is step 4, Forecast (§7), once the real ingest+features run is verified.

Follow the repo layout and module contracts already established in `backend/signals/` and `frontend/src/` (which mirror `md/architecture.md` §3 and §6) rather than inventing a new structure.

## Commands

Backend (from `backend/`, via `uv`):

```
uv sync                    # install/sync dependencies
uv run pytest -q           # run tests
uv run signals ingest      # pull ArcGIS layers -> data/raw/*.parquet + DuckDB (long-running, ~15-30 min)
uv run signals features    # build sales_clean + bg_features
uv run signals train       # train/fallback + score all block groups
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

The LLM's role in the product is **interpretation only** (OpenAI via `brief.py`, model from `OPENAI_MODEL`): a `/brief` endpoint turns a block's structured summary into a one-page outreach brief. It explains scores; it never computes them.

## Planned architecture

FastAPI backend + React (Vite) frontend, Leaflet map, SQLite/DuckDB local store.

Backend pipeline is a linear chain of modules, each consuming the previous one's output:

- `ingest.py` — Detroit Open Data Portal ArcGIS REST endpoints (Parcels, Building Permits, Blight Violations) → local DB
- `features.py` — aggregate parcel/permit/sales rows to block or block-group level; join Census ACS tenure/income
- `forecast.py` — gradient-boosted model, features at year T predict growth at T+2 → heat score + top contributing features
- `vulnerability.py` — rank owner-occupied parcels on hot blocks
- `/brief` — OpenAI call with a strict output schema

Frontend is two screens: heat map, and a block drawer with ranked households plus a "Generate brief" button.

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
