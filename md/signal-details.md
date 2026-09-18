# Why It Can Win

- Future of Detroit in a form residents care about: growth is coming, and this decides who benefits from it.
- Input → intelligence → action in one screen: a map lights up, a list of households appears, a brief is ready to hand to canvassers.
- Built entirely on public data that is already published and queryable, so no partner agreement is needed.
- Distinct from the other housing ideas in the pool. HomeKeep and Appeal Autopilot help a household that already knows it needs help; Signals finds the households that do not know yet and can hand them off to those tools.
- Optional stretch layer ties directly to a live policy debate: simulate how a split-rate land value tax would shift bills for speculators versus homeowners on each block.

## Partner Alignment

| Partner | Fit | Angle |
|---|---|---|
| **Gilbert Family Foundation** | Very high | Neighborhood stabilization and keeping legacy residents in place as investment arrives. A targeting tool for the organizations they fund. |
| **City of Detroit** | High | Housing & Revitalization and the Assessor both need to see pressure before it becomes displacement. Supports equitable-growth goals with the City's own data. |
| **Invest Detroit Ventures** | Medium-high | Neighborhood-change forecasting sells to CDFIs, land trusts, and cities; the same model has a commercial variant for mission-driven developers. |
| **Detroit Development Fund** | Medium | Shows where small-business and home-repair lending will have the most stabilizing effect before prices move. |
| **TechTown Detroit** | Medium | Open block-level scoring data other builders can reuse. |

## Business Case

- **Target user:** an outreach lead at a CDO, land trust, or housing counseling agency deciding which blocks and households to reach this month. Residents never pay.
- **Revenue:** per-organization SaaS for CDOs, CDFIs, and land trusts; city licenses for housing departments. Foundations can fund seats for their grantee cohorts.
- **Expansion:** every city with parcel, permit, and sales data has the same displacement-timing problem. The pipeline ports to any open data portal.

## Implementation

### Architecture

- FastAPI backend. `ingest.py` pulls Parcels (assessed values, ownership, sales, zoning), Building Permits, and Blight Violations from the Detroit Open Data Portal ArcGIS REST endpoints and loads them into SQLite or DuckDB locally. Queries return at most 1,000 records, so paginate with `resultOffset`.
- `features.py` aggregates to the block or block-group level: permit counts and value over time, median sale price trend, LLC and non-Detroit owner share, vacancy, distance to active corridors. Join Census ACS tenure and income.
- `forecast.py` trains a gradient-boosted model on historical windows (features at year T predict price or permit growth at T+2). Output: heat score 0–100 with top contributing features.
- `vulnerability.py` ranks owner-occupied parcels on hot blocks by exemption status, delinquency signals, tenure, and ownership-name heuristics for likely heirship.
- `/brief` endpoint sends the block's structured summary to an LLM (OpenAI) with a strict schema and returns a one-page outreach brief.
- React + Vite: heat map, block drawer with ranked households (anonymized in the demo), and a "Generate brief" button. Two screens.

### Prepare before the weekend

- [ ] Pull Parcels, Building Permits, and Blight Violations locally; confirm which ownership, sale, and exemption fields the parcel file actually exposes.
- [ ] Confirm whether a separate property sales history dataset is available or whether the parcel file's most-recent-sale fields are all you get; this decides how far back the forecast can train.
- [ ] Register a Census API key and pull ACS tenure, income, and age by block group.
- [ ] Pick two demo corridors where permits have visibly accelerated, plus one control area.

### Cut-line

- **Drop first:** land value tax simulator, Census join, per-household ranking (fall back to block-level only).
- **Keep:** block heat score → map → outreach brief.
- If historical sales depth is thin, replace the trained forecast with a transparent weighted index and say so.

### The 3-minute demo

1. Open the map. Three blocks near an active corridor glow red; a control neighborhood stays cool. Click one: "Permits up sharply over two years, LLC buyers now a large share of recent sales."
2. The drawer lists owner-occupied homes on the block ranked by exposure, each with its reasons (anonymized for the demo).
3. Click "Generate brief." A one-page canvassing plan appears. Close: *"Detroit is growing. This decides whether the people who stayed get to stay."*

## Risks

- **Targeting perception.** A list of vulnerable households could be misused by speculators. Keep household-level views behind organization accounts, show only block-level scores publicly, and say so on the slide.
- **Forecast credibility.** Limited history means weak validation. Backtest on one past window, show the result honestly, and lead with explainability.
- **Heirship inference.** Name-matching is noisy. Label it a flag for follow-up, never a determination.

## Resources

- [Detroit Open Data Portal](https://data.detroitmi.gov/)
- [Parcels (Current) – ArcGIS REST endpoint](https://services2.arcgis.com/qvkbeam7Wirps6zC/ArcGIS/rest/services/parcel_file_current/FeatureServer/0)
- [Detroit Land Value Tax Plan](https://detroitmi.gov/lvt)
- [Census Data API](https://www.census.gov/data/developers.html)
