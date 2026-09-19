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
