/**
 * Neighborhoods ranked by investment pressure. Every row shows all three
 * ranking numbers so the order never looks arbitrary, and the sort toggle is
 * client-side over the already-fetched rows — the real data genuinely
 * disagrees about what "most at risk" means (one block group at 100 vs six of
 * nine above the threshold), so both orders are offered rather than one being
 * picked silently.
 */
import type { NeighborhoodRow } from "../api";
import { heatColor, inkOn } from "../heat";
import { SORT_OPTIONS, type SortKey } from "../neighborhoods";

interface NeighborhoodListProps {
  rows: NeighborhoodRow[];
  hotThreshold: number;
  sort: SortKey;
  onSortChange: (key: SortKey) => void;
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
}

export function NeighborhoodList({
  rows, hotThreshold, sort, onSortChange, selectedSlug, onSelect,
}: NeighborhoodListProps) {
  return (
    <>
      <div className="nb-sort" role="group" aria-label="Sort neighborhoods">
        {SORT_OPTIONS.map((option) => (
          <button
            key={option.key}
            type="button"
            title={option.hint}
            aria-pressed={sort === option.key}
            className={sort === option.key ? "nb-sort-btn active" : "nb-sort-btn"}
            onClick={() => onSortChange(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="muted">No neighborhoods to show.</p>
      ) : (
        <ol className="nb-list">
          {rows.map((row) => (
            <li key={row.slug}>
              <button
                type="button"
                className={row.slug === selectedSlug ? "nb-row active" : "nb-row"}
                aria-current={row.slug === selectedSlug}
                onClick={() => onSelect(row.slug)}
              >
                <span
                  className="nb-row-heat"
                  style={{ background: heatColor(row.heat_max), color: inkOn(heatColor(row.heat_max)) }}
                >
                  {row.heat_max}
                </span>
                <span className="nb-row-body">
                  <span className="nb-row-name">{row.name}</span>
                  <span className="muted nb-row-meta">
                    {row.n_hot} of {row.n_block_groups} block group{row.n_block_groups === 1 ? "" : "s"} at{" "}
                    {hotThreshold}+ · avg {row.heat_mean}
                    {row.n_low_confidence > 0 && ` · ${row.n_low_confidence} low confidence`}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
