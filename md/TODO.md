# Signals — Manual TODO

Things only you can do. Everything else is code and is tracked in `architecture.md` §7.

**Status:** all eight build steps are done — the full demo path runs end to end (map → drawer → ranked households → outreach brief) with demo fly-to presets, offline/not-scored banners, and run instructions in the README. What's left is yours: confirm or replace the suggested corridors (D.1), the protections list (D.2), logistics (E), the post-run checks (F), and the deployment decision (Vercel static export vs. a hosted backend — see the conversation on 2026-09-18). Your open red items are D.1 (demo corridors — the data now offers candidates, see below) and section E (deadline, ownership).

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
- No keys are needed for Detroit ArcGIS layers or the basemap (Esri light-gray canvas; CARTO turned out to require one).

## B. Local toolchain — done

- [x] `uv` and Node 20+ (v26.8.2) installed.
- [x] Scaffolding in (`backend/`, `frontend/`); dependencies synced (`uv sync`, `npm install`), tests pass, both dev servers boot. Re-run either sync command after pulling changes on another machine.

## C. Data pulls you must run

- [x] 🔴 **Run the full ingest** — done 2026-09-18 in 10 minutes with zero retries after the keyset-pagination fix. Every layer's row count matches the live total. On disk: 118 MB of parquet in `backend/data/raw/` + a 176 MB `signals.duckdb` ≈ 295 MB total, all local.
  ```
  cd backend && uv run signals ingest
  ```
  Roughly 1,870 paginated requests (378k parcels, 538k sales, 47k permits, **905k blight tickets** — the biggest layer —, 625 block groups). With keyset pagination (fixed after the first run died on the sales layer) expect roughly 10–15 minutes. If a run dies, rerun with `--resume` to skip layers already saved under `backend/data/raw/`. Leaves `backend/data/raw/*.parquet` and `backend/data/signals.duckdb`, both entirely on your local disk (no cloud storage involved). Start it and keep doing other things (e.g. section D.1 or E below); nothing downstream can be tested until it finishes. First run will also download DuckDB's spatial extension (needs internet once).
- [ ] 🟡 **Spot-check 3 parcels you personally know** (your block, a relative's house) in `raw_parcels`:
  - Does `pct_pre_claimed` match whether they actually have the exemption?
  - Does `taxpayer_address` equal `address` for owner-occupants?
  - Does `taxpayer_1` look like a person for owner-occupied homes and an LLC for rentals?
  This validates the owner-occupied rule in `vulnerability.py`. If it's wrong, say so and we change the rule.
- [x] 🟡 **Check blight tickets after ingest** — 904,905 rows, real coverage 2005 → present (40k–90k tickets/year), so `blight_tickets` is a solid feature, kept. 56 junk rows dated 2027–8535 and 8 dated before 2000 are dropped by `features.py`.
- [ ] 🟢 **Re-run `uv run signals ingest --since <date>`** the morning of the demo for fresh permits and sales, then `features`, `train`, `score`.

## D. Decisions only you can make (local knowledge)

- [ ] 🔴 **Pick two demo corridors and one control area.** The app now ships three *suggested* presets as fly-to buttons ("Demo (suggested picks)" bar above the map): **Hubbard Richard** `261635211002` (Corktown/Mexicantown edge, heat 100, brief already cached), **McDougall-Hunt** `261635190002` (beside Eastern Market, heat 99), and **University District** `261635384002` as the control (heat 9, 70% owner-occupied). To make them yours, edit `DEMO_CORRIDORS` in `backend/signals/demo.py` and set `suggested: False`; the bar updates on the next API restart. Other strong hot candidates with ≥8 sales: Five Points, Nardin Park, Dexter-Linwood, Riverbend, Fitzgerald/Marygrove, Pingree Park. The real feature table already points at candidates (2025 data): highest price-per-sqft block groups are Brush Park, Midtown, Corktown, Cultural Center, Downtown, Rivertown; highest 2025 permit value are Elijah McCoy / New Center ($1.07B — the hospital build), Delray (bridge), Milwaukee Junction (75% LLC buyers), Brush Park. A displacement story wants a *residential* block group that is heating up but hasn't fully flipped — Milwaukee Junction, Elmwood Park, Springwells, and the Corktown/Core City edge look like the interesting ones; Brush Park is already gone. Original candidate list:
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
  Add, remove, or rename. This is `config.PROTECTIONS` today (five entries; Make It Home isn't in it yet — add it if you want the brief to recommend it). The prompt is forbidden from recommending anything else, and `brief.py` strips unlisted names as a second guard. Cached briefs under `backend/data/briefs/` should be regenerated (`uv run signals brief <geoid> --force`) after you change the list.
- [ ] 🟡 **Find a real tax-delinquency or foreclosure source.** Search https://data.detroitmi.gov and the Wayne County Treasurer site for a parcel-level delinquent-taxes or foreclosure-list dataset (CSV or ArcGIS). None of the layers I verified carry delinquency.
  If nothing public exists, approve the proxy: unpaid blight balance + parcel `tax_status`, labelled "delinquency proxy" in the UI.
- [ ] 🟡 **Approve the demo anonymization rule** — now implemented exactly this way; open a hot block group with `SIGNALS_DEMO=1` and check the drawer: names dropped, address shown as hundred-block ("3800 block of CORTLAND"), no parcel ID. Heirship label reads *"Possible heirs' property: follow up, not a determination"* plus the cue that triggered it. Also decide whether the non-demo (org) view should show the taxpayer name at all — it currently does.
- [ ] 🟢 **Decide the hot threshold** for household ranking (default: heat score ≥ 70). Lower it if too few block groups qualify in the demo corridors.

## E. Buildathon logistics

- [ ] 🔴 **Confirm submission format**: live demo or video, time limit, whether judges want a repo link, and the deadline. Tell me the deadline so build order can be cut accordingly.
- [ ] 🔴 **Assign ownership** if there is more than one builder: backend pipeline vs frontend map. Otherwise I build in the milestone order in `architecture.md` §7.
- [ ] 🟢 **Draft the 3-minute demo script** from `signal-details.md` "The 3-minute demo". The risks slide must state the household-gating policy out loud.
- [ ] 🟢 **Assume bad venue Wi-Fi**: everything runs locally from DuckDB except `/brief`. Pre-generate the briefs for your demo block groups the morning of — `cd backend && uv run signals brief <geoid> <geoid> …` — and they're served from `backend/data/briefs/` with no network. (Hubbard Richard, `261635211002`, is already cached from the first live run.) Do the same for the neighborhoods page — `uv run signals explain <slug…>` caches under `backend/data/explainers/` (Bethune Community is already cached).

## F. After the first end-to-end run

- [ ] 🟡 **Decide trained model vs fallback index** (`backend/data/models/backtest_report.json` has everything). Numbers as of 2026-09-18, holdout 2023: trained model Spearman **0.39** (0.31 on 2022), R² 0.10, MAE 0.215 vs 0.229 for guessing the mean — auto-mode keeps the trained model. Transparent index (sign-corrected): +0.13 to +0.32 across 2019–2023. Two things to know before you choose: (1) the model's strongest signal is a *dip* in last year's price — in block groups with 5–10 sales a year a one-year spike reverts, so "prices fell last year" reads as hot; the drawer copy needs to say that plainly. (2) The first draft of the index weighted momentum positively and was anti-predictive on every holdout year; that's fixed, but it's a reminder that the index's weights are backtested, not gospel. Recommendation: ship the trained model, show the 0.39 on the slide, and keep `MODEL_MODE=fallback` as the one-line escape hatch.
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
- ✅ Ingest (build-order step 2): `ingest.py`'s ArcGIS paginator is implemented — pagination, retry/backoff, incremental `--since` refresh, and `parcel_id` normalization all covered by 13 unit tests against a mocked transport, plus a live smoke test against all five real endpoints (sales, permits, blight, parcels with centroids, block groups with polygons). Nobody has run the full pull yet — that's C.1 above.
- ✅ Ingest's arm's-length sale filter is now grounded in real data, not a guess: `term_of_sale` is a controlled vocabulary and exactly two of ~15 categories are genuinely arm's-length (`03-ARM'S LENGTH`, `19-MULTI PARCEL ARM'S LENGTH`), confirmed via a live stats query against all 537,595 sales rows. See `architecture.md` §1.
- ✅ Polish (build-order step 8): `GET /api/demo/corridors` + a preset bar with fly-to buttons (suggested picks until D.1 is done), API-offline and not-yet-scored banners with the exact command to run, a loading skeleton in the drawer, run instructions in the root README and a real `frontend/README.md`.
- ✅ Brief (build-order step 7, demo milestone 3): `brief.py` builds an aggregate-only `BlockSummary` (score, labelled signals, five complete years of trend, counts of household reasons — never a household row, name, or address), sends it to the OpenAI Responses API with a strict schema derived from the `Brief` model, and drops any protection not on `config.PROTECTIONS` even if the model names one. Briefs are cached as JSON under `backend/data/briefs/` keyed by GEOID + model version + LLM model, so a second click is instant and offline; `uv run signals brief <geoid…>` pre-generates them (your E.4 Wi-Fi item). `POST /api/blocks/{geoid}/brief` (+`?force=true`) is gated. 63 backend tests.
- ✅ Vulnerability (build-order step 6, demo milestone 2): `vulnerability.py` ranks owner-occupied residential parcels (class 401/407; PRE claimed, or mailing address matches the home by number + street and the taxpayer isn't an entity) on block groups with heat ≥ 70. Terms: missing PRE 3.0, unpaid blight balance 2.0 (delinquency proxy), tenure 0.1/yr capped at 30, taxable-vs-assessed gap ×2.0, heirship flag 1.0 (estate/heirs wording, or surname ≠ last buyer with 15+ years tenure) — every term writes its own reason string. `GET /api/blocks/{geoid}/households` computes it live (40–70 ms on real block groups of 86–167 households); `SIGNALS_DEMO=1` strips names + parcel ids and reduces addresses to the hundred-block; `uv run signals rank` precomputes `parcel_vulnerability` for inspection. Rules were checked against the real parcel file (see `architecture.md` §6). 55 backend tests.
- ✅ API + map (build-order step 5, demo milestone 1): `GET /api/blocks` serves the 625 block-group polygons joined to scores (575 KB, ~40 ms cold / ~10 ms cached, cache keyed on `scored_at`); `GET /api/blocks/{geoid}` adds labelled signals, per-year trend series with the partial current year flagged, and the model footnote. Read-only DuckDB connection per request, CORS for the Vite dev origin. Frontend: single-hue red sequential ramp (7 steps), hairline borders, dashed border for low-confidence block groups, persistent legend, hover tooltip, fly-to on select, drawer with heat badge, signal sentences, and five single-series sparklines. 46 backend tests; frontend type-checks and builds.
- ✅ Forecast (build-order step 4): `forecast.py` trains a gradient-boosted model on 2,626 (block group, year) rows, backtests on the latest complete window, refits, scores all 625 block groups into `bg_scores` with top-3 signals and a confidence flag, and ships a sign-checked transparent fallback index. First real run exposed two design bugs — price-level features produced pure mean reversion, and the draft index had momentum wrong-signed — both fixed on evidence and documented in `architecture.md` §6. 40 tests pass.
- ✅ Geo + features (build-order step 3) implemented **and verified on the real pull**: 377,892 of 377,940 parcels matched to a block group (48 outliers); `sales_clean` = 110,097 arm's-length sales (40% LLC buyers, 12% out-of-state taxpayers); `bg_features` = 10,000 rows. From 2014 on, 470–550 of 625 block groups have ≥3 sales a year, so the forecast has a real training set. A first real-data bug (junk blight dates stretching the year grid to 6,525 years) was caught and fixed with a regression test. 32 tests pass.
