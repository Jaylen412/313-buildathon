/**
 * Neighborhoods ranked by investment pressure. Every row shows all three
 * ranking numbers (hot blocks, average, hottest block) regardless of sort, so
 * the order never hides context; the sort control (name or score, each
 * ascending/descending) is a dropdown, client-side over the already-fetched
 * rows.
 */
import { useState } from "react";
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
  const [sortOpen, setSortOpen] = useState(false);
  // the control starts as an icon-only button; the label box appears once the
  // user has opened it at least once, and stays revealed after that
  const [everOpened, setEverOpened] = useState(false);
  const current = SORT_OPTIONS.find((option) => option.key === sort) ?? SORT_OPTIONS[0];

  function choose(key: SortKey) {
    onSortChange(key);
    setSortOpen(false);
  }

  function handleToggleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      setSortOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setSortOpen(true);
      setEverOpened(true);
      const idx = SORT_OPTIONS.findIndex((option) => option.key === sort);
      const step = event.key === "ArrowDown" ? 1 : -1;
      onSortChange(SORT_OPTIONS[(idx + step + SORT_OPTIONS.length) % SORT_OPTIONS.length].key);
    }
  }

  return (
    <>
      <div
        className="nb-sort"
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setSortOpen(false);
        }}
      >
        <button
          type="button"
          className={everOpened ? "nb-sort-toggle" : "nb-sort-toggle collapsed"}
          aria-haspopup="listbox"
          aria-expanded={sortOpen}
          aria-label={`Sort neighborhoods: ${current.label}`}
          title={current.hint}
          onClick={() => {
            setSortOpen((open) => !open);
            setEverOpened(true);
          }}
          onKeyDown={handleToggleKeyDown}
        >
          <span className="material-symbols-outlined nb-sort-icon" aria-hidden="true">sort</span>
          {everOpened && (
            <>
              <span className="nb-sort-label">{current.label}</span>
              <span className="material-symbols-outlined nb-sort-caret" aria-hidden="true">
                {sortOpen ? "expand_less" : "expand_more"}
              </span>
            </>
          )}
        </button>
        {sortOpen && (
          <ul className="nb-sort-menu" role="listbox" aria-label="Sort neighborhoods">
            {SORT_OPTIONS.map((option) => (
              <li
                key={option.key}
                role="option"
                aria-selected={sort === option.key}
                title={option.hint}
                className={sort === option.key ? "nb-sort-option active" : "nb-sort-option"}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(option.key)}
              >
                {option.label}
              </li>
            ))}
          </ul>
        )}
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
