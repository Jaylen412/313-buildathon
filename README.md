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