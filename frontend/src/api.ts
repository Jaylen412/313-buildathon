/**
 * Typed fetchers for the Signals API. Contract: md/architecture.md §6.
 * Household and brief calls need VITE_ORG_TOKEN (frontend/.env.local) — see
 * md/TODO.md section A.2 for what that token is and why.
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const ORG_TOKEN = import.meta.env.VITE_ORG_TOKEN as string | undefined;

export interface TopSignal {
  feature: string;
  value: number;
  z: number;
  direction: "up" | "down";
}

export interface BlockFeature {
  type: "Feature";
  geometry: GeoJSON.Geometry;
  properties: {
    bg_geoid: string;
    heat_score: number;
    top_signals: TopSignal[];
    neighborhood: string;
  };
}

export interface BlocksResponse {
  type: "FeatureCollection";
  features: BlockFeature[];
}

export interface BlockDetail {
  bg_geoid: string;
  neighborhood: string;
  heat_score: number;
  top_signals: TopSignal[];
  trend: Record<string, number[]>;
  model_mode: "trained" | "fallback";
  backtest_summary?: string;
}

export interface Household {
  parcel_id?: string; // absent in demo mode
  address: string; // hundred-block in demo mode
  score: number;
  reasons: string[];
  heirship_flag: boolean;
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

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...options.headers },
  });
  if (!res.ok) {
    throw new Error(`${options.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function orgHeaders(): HeadersInit {
  if (!ORG_TOKEN) {
    throw new Error("VITE_ORG_TOKEN is not set (frontend/.env.local)");
  }
  return { "X-Org-Token": ORG_TOKEN };
}

export const fetchBlocks = () => apiFetch<BlocksResponse>("/api/blocks");

export const fetchBlockDetail = (geoid: string) =>
  apiFetch<BlockDetail>(`/api/blocks/${geoid}`);

export const fetchHouseholds = (geoid: string) =>
  apiFetch<Household[]>(`/api/blocks/${geoid}/households`, { headers: orgHeaders() });

export const generateBrief = (geoid: string) =>
  apiFetch<Brief>(`/api/blocks/${geoid}/brief`, { method: "POST", headers: orgHeaders() });
