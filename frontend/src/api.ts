/**
 * Typed fetchers for the Signals API. Contract: md/architecture.md §6.
 * Household and brief calls need VITE_ORG_TOKEN (frontend/.env.local) — see
 * md/TODO.md section A.2 for what that token is and why.
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const ORG_TOKEN = import.meta.env.VITE_ORG_TOKEN as string | undefined;

export type Confidence = "ok" | "low";
export type ModelMode = "trained" | "fallback";

export interface TopSignal {
  feature: string;
  label: string;
  value: number;
  z: number;
  direction: "up" | "down";
  weight: number;
}

export interface BlockProperties {
  bg_geoid: string;
  neighborhood: string | null;
  heat_score: number | null;
  confidence: Confidence | null;
  top_signals: TopSignal[];
  model_mode: ModelMode | null;
}

export interface BlockFeature {
  type: "Feature";
  geometry: GeoJSON.Geometry;
  properties: BlockProperties;
}

export interface BlocksResponse {
  type: "FeatureCollection";
  features: BlockFeature[];
}

export interface Trend {
  years: number[];
  series: Record<string, (number | null)[]>;
  partial_year: number | null;
}

export interface BlockDetail {
  bg_geoid: string;
  neighborhood: string | null;
  heat_score: number;
  predicted_growth: number | null;
  confidence: Confidence;
  top_signals: TopSignal[];
  model_version: string;
  model_mode: ModelMode;
  scored_at: string;
  trend: Trend;
  backtest_summary: string;
}

export interface Household {
  parcel_id?: string; // absent in demo mode
  owner?: string | null; // absent in demo mode
  address: string; // hundred-block in demo mode
  rank: number;
  score: number;
  reasons: string[];
  heirship_flag: boolean;
  tenure_years: number | null;
  has_pre: boolean;
  unpaid_blight_balance: number;
  uncapping_gap: number | null;
}

export interface HouseholdsResponse {
  bg_geoid: string;
  hot: boolean;
  hot_threshold: number;
  anonymized: boolean;
  heirship_note: string;
  households: Household[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface Protection {
  name: string;
  who_qualifies: string;
  first_step: string;
}

export interface Brief {
  headline: string;
  what_is_changing: string[];
  why_it_matters: string;
  protections_to_offer: Protection[];
  canvassing_plan: string[];
  caveats: string[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

function orgHeaders(): HeadersInit {
  if (!ORG_TOKEN) {
    throw new ApiError(0, "VITE_ORG_TOKEN is not set (frontend/.env.local)");
  }
  return { "X-Org-Token": ORG_TOKEN };
}

export interface Corridor {
  key: string;
  label: string;
  bg_geoid: string;
  why: string;
  suggested: boolean;
  neighborhood: string | null;
  heat_score: number | null;
  confidence: Confidence | null;
}

export interface Health {
  ok: boolean;
  scored_model_mode: ModelMode | null;
  scored_at: string | null;
  n_scored: number;
  demo: boolean;
}

export const fetchHealth = () => apiFetch<Health>("/api/health");

export const fetchCorridors = () => apiFetch<Corridor[]>("/api/demo/corridors");

export const fetchBlocks = () => apiFetch<BlocksResponse>("/api/blocks");

export const fetchBlockDetail = (geoid: string) => apiFetch<BlockDetail>(`/api/blocks/${geoid}`);

export const HOUSEHOLDS_PAGE_SIZE = 25;

export const fetchHouseholds = (geoid: string, offset = 0, limit = HOUSEHOLDS_PAGE_SIZE) =>
  apiFetch<HouseholdsResponse>(`/api/blocks/${geoid}/households?limit=${limit}&offset=${offset}`, {
    headers: orgHeaders(),
  });

export interface BriefResponse {
  bg_geoid: string;
  neighborhood: string | null;
  cached: boolean;
  llm_model: string;
  brief: Brief;
}

export const generateBrief = (geoid: string, force = false) =>
  apiFetch<BriefResponse>(`/api/blocks/${geoid}/brief${force ? "?force=true" : ""}`, {
    method: "POST",
    headers: orgHeaders(),
  });

/**
 * Neighborhoods. A neighborhood is the set of block groups sharing a
 * parcel-file neighborhood name (186 names over 625 block groups), rolled up
 * in deterministic SQL — not a second model. `mean_z` is an average of
 * separate per-block-group comparisons, so it is NOT a z-score for the
 * neighborhood: only ever render a signal as "in k of n block groups".
 */
export type SignalDirection = "up" | "down" | "mixed";

export interface AggregateSignal {
  feature: string;
  label: string;
  direction: SignalDirection;
  mean_z: number;
  n_members: number;
  n_block_groups: number;
  n_up: number;
  n_down: number;
}

export interface NeighborhoodRow {
  name: string;
  slug: string;
  n_block_groups: number;
  n_hot: number;
  heat_max: number;
  heat_mean: number;
  hottest_geoid: string;
  n_low_confidence: number;
  top_signals: AggregateSignal[];
}

export interface NeighborhoodsResponse {
  hot_threshold: number;
  neighborhoods: NeighborhoodRow[];
}

export interface NeighborhoodMember {
  bg_geoid: string;
  heat_score: number;
  confidence: Confidence;
  top_signals: TopSignal[];
}

export interface NeighborhoodDetail extends NeighborhoodRow {
  /** Position among `n_neighborhoods` scored neighborhoods, most pressure first. */
  rank: number;
  n_neighborhoods: number;
  /** Lowest-scoring member block group; with heat_max it gives the spread. */
  heat_min: number;
  hot_threshold: number;
  model_mode: ModelMode;
  scored_at: string;
  backtest_summary: string;
  trend: Trend;
  block_groups: NeighborhoodMember[];
}

export interface NeighborhoodSummaryResponse {
  name: string;
  slug: string;
  cached: boolean;
  llm_model: string;
  /** One paragraph of plain prose explaining what the metrics add up to. */
  summary: string;
}

export const fetchNeighborhoods = () => apiFetch<NeighborhoodsResponse>("/api/neighborhoods");

export const fetchNeighborhood = (slug: string) =>
  apiFetch<NeighborhoodDetail>(`/api/neighborhoods/${encodeURIComponent(slug)}`);

export const generateNeighborhoodSummary = (slug: string, force = false) =>
  apiFetch<NeighborhoodSummaryResponse>(
    `/api/neighborhoods/${encodeURIComponent(slug)}/summary${force ? "?force=true" : ""}`,
    { method: "POST", headers: orgHeaders() },
  );
