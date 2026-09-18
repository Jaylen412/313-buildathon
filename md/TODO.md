# Signals — Manual TODO

Things only you can do. Everything else is code and is tracked in `architecture.md` §7.

**Status:** scaffolding is done (backend + frontend both boot, tests pass). Currently building build-order step 2, `ingest.py` (the ArcGIS paginator) — that's my work, not yours. The real blockers on your side right now are section D.1 (demo corridors) and section E (deadline, ownership).

Urgency: 🔴 do now · 🟡 before the first end-to-end run · 🟢 before the demo

---

## A. Accounts & keys

- [x] 🔴 **Put your existing OpenAI API key** in `backend/.env` as `OPENAI_API_KEY`. Optionally set `OPENAI_MODEL` to override the default model.
  Unblocks: `/brief` endpoint (milestone 3). Everything else runs without it.
- [x] 🔴 **Pick an org token.** This is just a password you invent, not something you sign up for. Generate any long random string (`openssl rand -hex 24`) and put it in two places: `backend/.env` as `SIGNALS_ORG_TOKEN` and `frontend/.env.local` as `VITE_ORG_TOKEN`.
  Why: the spec requires household-level data to sit behind organization accounts. Real login is out of scope, so one shared secret stands in for it. The frontend sends it as the `X-Org-Token` header; the backend only returns household rows and briefs when it matches. Without it, callers see block-level scores only.
  Unblocks: gated households endpoint (milestone 2).
- [ ] 🟢 *(stretch only)* **Register a Census API key** at https://api.census.gov/data/key_signup.html → `CENSUS_API_KEY`.
  Only needed if the ACS join survives the cut-line. Skip until milestone 3 is done.
- No keys are needed for Detroit ArcGIS layers or the CARTO basemap.

## B. Local toolchain — done

- [x] `uv` and Node 20+ (v26.8.2) installed.
- [x] Scaffolding in (`backend/`, `frontend/`); dependencies synced (`uv sync`, `npm install`), tests pass, both dev servers boot. Re-run either sync command after pulling changes on another machine.

## C. Data pulls you must run

- [ ] 🔴 **Run the full ingest** as soon as `ingest.py` is implemented (I'll flag it here when it's ready):
  ```
  cd backend && uv run signals ingest
  ```
  Roughly 1,000 paginated requests (378k parcels, 537k sales, 47k permits, blight, block groups). Expect 15–30 minutes. Leaves `backend/data/raw/*.parquet` and `backend/data/signals.duckdb`. Start it and keep doing other things; nothing downstream can be tested until it finishes.
- [ ] 🟡 **Spot-check 3 parcels you personally know** (your block, a relative's house) in `raw_parcels`:
  - Does `pct_pre_claimed` match whether they actually have the exemption?
  - Does `taxpayer_address` equal `address` for owner-occupants?
  - Does `taxpayer_1` look like a person for owner-occupied homes and an LLC for rentals?
  This validates the owner-occupied rule in `vulnerability.py`. If it's wrong, say so and we change the rule.
- [ ] 🟡 **Check blight tickets after ingest**: row count and earliest `ticket_issued_date`. I didn't inspect this layer. If it only goes back a couple of years, `blight_tickets` becomes a weak feature and we drop it.
- [ ] 🟢 **Re-run `uv run signals ingest --since <date>`** the morning of the demo for fresh permits and sales, then `features`, `train`, `score`.

## D. Decisions only you can make (local knowledge)

- [ ] 🔴 **Pick two demo corridors and one control area.** Candidates to check *against the data*, not assumptions:
  - Hot: Corktown / Core City, Milwaukee Junction / North End, Jefferson-Chalmers, Livernois "Avenue of Fashion", Islandview / West Village, Bagley / Fitzgerald
  - Control: a stable far-west or far-east residential neighborhood with flat permits
  After the first `score` run, open the map and confirm your picks actually light up. Record the chosen block-group GEOIDs in `backend/signals/demo.py` (I'll leave placeholders).
  Unblocks: demo fly-to presets and the sanity check in §7 step 3.
- [ ] 🟡 **Vet the protections list the brief may recommend.** Draft list, verify each name and eligibility on detroitmi.gov or with a housing counselor:
  - Principal Residence Exemption (PRE)
  - HOPE — Homeowners Property Exemption (Detroit's poverty tax exemption)
  - Pay As You Stay (PAYS) — Wayne County delinquency payment plan
  - Detroit Tax Relief Fund (Gilbert Family Foundation / Wayne Metro)
  - Make It Home (UCHC) — for occupied homes facing foreclosure
  - Heirs' property / probate assistance (UCHC, Michigan Legal Services, Detroit Justice Center)
  Add, remove, or rename. This becomes `config.PROTECTIONS`; the brief prompt is forbidden from recommending anything not on it.
  Unblocks: `brief.py` (milestone 3).
- [ ] 🟡 **Find a real tax-delinquency or foreclosure source.** Search https://data.detroitmi.gov and the Wayne County Treasurer site for a parcel-level delinquent-taxes or foreclosure-list dataset (CSV or ArcGIS). None of the layers I verified carry delinquency.
  If nothing public exists, approve the proxy: unpaid blight balance + parcel `tax_status`, labelled "delinquency proxy" in the UI.
- [ ] 🟡 **Approve the demo anonymization rule**: names dropped, address shown as hundred-block ("1400 block of Vinewood St"), no parcel ID. Also approve the heirship label wording: *"Possible heirs' property: follow up, not a determination."*
- [ ] 🟢 **Decide the hot threshold** for household ranking (default: heat score ≥ 70). Lower it if too few block groups qualify in the demo corridors.

## E. Buildathon logistics

- [ ] 🔴 **Confirm submission format**: live demo or video, time limit, whether judges want a repo link, and the deadline. Tell me the deadline so build order can be cut accordingly.
- [ ] 🔴 **Assign ownership** if there is more than one builder: backend pipeline vs frontend map. Otherwise I build in the milestone order in `architecture.md` §7.
- [ ] 🟢 **Draft the 3-minute demo script** from `signal-details.md` "The 3-minute demo". The risks slide must state the household-gating policy out loud.
- [ ] 🟢 **Assume bad venue Wi-Fi**: everything runs locally from DuckDB except `/brief`. Pre-generate and cache the briefs for your demo block groups the morning of (`POST /api/blocks/{geoid}/brief` once each) so the demo works offline.

## F. After the first end-to-end run

- [ ] 🟡 **Read `backend/data/models/backtest_report.json`.** Decide trained model vs fallback index from the numbers. Rule of thumb: Spearman ρ under 0.2 on the holdout → ship the fallback index and say so. Either way the number goes on the slide.
- [ ] 🟡 **Sanity-check the top 10 hottest block groups** on the map against your intuition. Note surprises; they are either bugs or the explainability story.
- [ ] 🟢 **Read one generated brief end to end** and flag anything that sounds like a determination rather than a prompt for follow-up.

---

## Already resolved

- ✅ Sales history exists as a separate layer (`assessor_property_sales_view`, 2011 → present, ~537k rows). The trained forecast is viable; fallback stays as a switch.
- ✅ Parcel field names confirmed against the live endpoint (see `architecture.md` §1).
- ✅ Geographic unit: census block group.
- ✅ `md/` is tracked in git.
- ✅ LLM provider: OpenAI (existing credits). `brief.py` uses the OpenAI SDK with structured outputs.
- ✅ Scaffolding (build-order step 1): backend (`uv`, FastAPI, DuckDB) and frontend (Vite + React + TypeScript, Leaflet, TanStack Query) both boot; `/api/health` live; gating verified against the real token (no token → 403, correct token → 501 not-yet-implemented); 5 backend tests pass; frontend type-checks and builds.
