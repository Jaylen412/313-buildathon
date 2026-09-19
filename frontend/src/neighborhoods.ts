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

export type SortKey = "name_asc" | "name_desc" | "score_asc" | "score_desc";

export const SORT_OPTIONS: { key: SortKey; label: string; hint: string }[] = [
  { key: "name_asc", label: "A-Z", hint: "alphabetically, A to Z" },
  { key: "name_desc", label: "Z-A", hint: "alphabetically, Z to A" },
  { key: "score_asc", label: "Score Low-High", hint: "by the highest-scoring block group, lowest first" },
  { key: "score_desc", label: "Score High-Low", hint: "by the highest-scoring block group, highest first" },
];

/**
 * The chosen key leads, then the same tiebreaks the API uses, so the order is
 * total and stable however it is sorted.
 */
export function sortRows(rows: NeighborhoodRow[], key: SortKey): NeighborhoodRow[] {
  const ranked = [...rows];
  ranked.sort((a, b) => {
    if (key === "name_asc") return a.name.localeCompare(b.name);
    if (key === "name_desc") return b.name.localeCompare(a.name);
    if (key === "score_asc" && a.heat_max !== b.heat_max) return a.heat_max - b.heat_max;
    if (b.heat_max !== a.heat_max) return b.heat_max - a.heat_max;
    if (b.n_hot !== a.n_hot) return b.n_hot - a.n_hot;
    if (b.heat_mean !== a.heat_mean) return b.heat_mean - a.heat_mean;
    return a.name.localeCompare(b.name);
  });
  return ranked;
}

/**
 * "1st", "2nd", "3rd", "11th" — English ordinals, teens included. Used for a
 * neighborhood's city rank, which the explainer paragraph may cite, so the
 * page has to show the same figure.
 */
export function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th";
  return `${n}${suffix}`;
}
