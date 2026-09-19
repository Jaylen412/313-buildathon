/**
 * Pure helpers for the neighborhoods page: name matching for the typeahead and
 * the client-side ranking. Kept out of the components so they stay testable
 * and Fast Refresh keeps working, matching heat.ts / severity.ts.
 */
import type { NeighborhoodRow } from "./api";

/**
 * Normalize a name the way slugs are built (drop apostrophes, periods and '#',
 * collapse everything else to single spaces) so "st marys" matches
 * "Crary/St Marys" and "ohair" matches "O'Hair Park".
 */
export function normalizeName(s: string): string {
  return s
    .toLowerCase()
    .replace(/['\u2019.#]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** Matches for a query, prefix hits first, otherwise in the order given. */
export function matchNeighborhoods(rows: NeighborhoodRow[], query: string): NeighborhoodRow[] {
  const q = normalizeName(query);
  if (!q) return rows;
  const prefix: NeighborhoodRow[] = [];
  const interior: NeighborhoodRow[] = [];
  for (const row of rows) {
    const name = normalizeName(row.name);
    if (name.startsWith(q)) prefix.push(row);
    else if (name.includes(q)) interior.push(row);
  }
  return [...prefix, ...interior];
}

export type SortKey = "heat_max" | "n_hot" | "heat_mean";

export const SORT_OPTIONS: { key: SortKey; label: string; hint: string }[] = [
  { key: "heat_max", label: "Hottest block", hint: "by the highest-scoring block group" },
  { key: "n_hot", label: "Most hot blocks", hint: "by how many block groups are above the threshold" },
  { key: "heat_mean", label: "Average", hint: "by the mean score across block groups" },
];

/**
 * Most at risk first. The chosen key leads, then the same tiebreaks the API
 * uses, so the order is total and stable however it is sorted.
 */
export function sortRows(rows: NeighborhoodRow[], key: SortKey): NeighborhoodRow[] {
  const ranked = [...rows];
  ranked.sort((a, b) => {
    if (key === "n_hot" && b.n_hot !== a.n_hot) return b.n_hot - a.n_hot;
    if (key === "heat_mean" && b.heat_mean !== a.heat_mean) return b.heat_mean - a.heat_mean;
    if (b.heat_max !== a.heat_max) return b.heat_max - a.heat_max;
    if (b.n_hot !== a.n_hot) return b.n_hot - a.n_hot;
    if (b.heat_mean !== a.heat_mean) return b.heat_mean - a.heat_mean;
    return a.name.localeCompare(b.name);
  });
  return ranked;
}
