# 📡 Signals

> **Brief:** Anti-displacement system forecasts which Detroit neighborhoods are about to grow from sales and investment pressure then identifies and ranks the long-time residents most at risk of displacement (no exemptions, delinquent taxes, tangled title) so community development organizations (**CDO**) can reach them before rising values and tax bills push them out.


## The Problem

Displacement in Detroit is usually noticed after it happens. By the time a corridor is "hot" long-time owners have already sold under pressure, fallen behind on higher tax bills, or lost homes they never had clear title to. The signs show up in public data months or years earlier — building permits clustering, sales prices jumping and LLCs buying adjacent lots.

Community development organizations, land trusts, and housing counselors have limited outreach hours. Less time should be spent figuring out who to prioritize. **Modify**: Signals handles which blocks and which households to reach first.

## Where the AI Lives in the Product

> 🧠 **Forecasting** — a block-level model predicts investment pressure over the next 12–36 months from permit velocity, sale-price trends, LLC and out-of-state buyer share, new construction, and proximity to active corridors. This is the judgment no one makes today at block resolution.
>
> **Prioritization** — the model ranks owner-occupied parcels on hot blocks by vulnerability: missing exemptions, tax delinquency signals, long tenure, likely heirship or tangled title. It decides who gets the first knock.
>
> **Interpretation** — an LLM writes a one-page outreach brief per block: what is changing, why it matters to these residents, and which protections to offer first. It explains the score; it does not compute it.
>
> **What stays in code:** feature engineering, the forecast, and the ranking are deterministic and inspectable. Every score shows its top contributing signals so an organizer can defend it.

## Business Case

- **Target user:** an outreach lead at a CDO, land trust, or housing counseling agency deciding which blocks and households to reach this month. Residents never pay.
- **Revenue:** per-organization SaaS for CDOs, CDFIs, and land trusts; city licenses for housing departments. Foundations can fund seats for their grantee cohorts.
- **Expansion:** every city with parcel, permit, and sales data has the same displacement-timing problem. The pipeline ports to any open data portal.

## Running Signals

Everything runs on one laptop from public data; only the outreach brief calls out (to OpenAI).

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/) (Python 3.12), Node 20+, an OpenAI API key.

```bash
# 1. secrets (never committed)
cp backend/.env.example backend/.env         # set OPENAI_API_KEY and SIGNALS_ORG_TOKEN (openssl rand -hex 24)
echo "VITE_ORG_TOKEN=<same token>" > frontend/.env.local

# 2. data pipeline (~10 min pull from Detroit's Open Data Portal, then seconds)
cd backend
uv sync
uv run signals ingest        # 5 ArcGIS layers -> data/raw/*.parquet + data/signals.duckdb (~295 MB, local)
uv run signals features      # parcel -> block-group join, block-group x year features, map polygons
uv run signals train         # forecast + backtest report + heat scores for all 625 block groups

# 3. run it
uv run signals serve         # API on http://127.0.0.1:8000
cd ../frontend && npm install && npm run dev   # map on http://localhost:5173
```

Optional: `uv run signals brief <geoid …>` pre-generates and caches outreach briefs so the demo works
without Wi-Fi; `uv run signals rank` precomputes the household ranking table for inspection;
`uv run signals ingest --resume` continues an interrupted pull; `uv run pytest` runs the backend tests.

`SIGNALS_DEMO=1` (default in `.env.example`) anonymizes the household view: names and parcel ids are
dropped and addresses become hundred-blocks. Household data is only served with the `X-Org-Token`
header; the public map and block scores never include it.

Design and data notes live in [`md/architecture.md`](md/architecture.md); the manual to-do list is
[`md/TODO.md`](md/TODO.md).
