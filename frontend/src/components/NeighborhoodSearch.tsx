/**
 * Typeahead over the neighborhood names. No dependency and no debounce: the
 * whole 186-row list is already in memory from the list query, so matching is
 * a sub-millisecond filter and debouncing would only add latency.
 *
 * Matching and name normalization live in ../neighborhoods so they stay pure
 * and testable; prefix matches sort ahead of interior ones.
 *
 * ARIA 1.2 combobox. `onMouseDown` is prevented on each option so focus never
 * leaves the input and the blur handler can't eat the click.
 */
import { useMemo, useRef, useState } from "react";
import type { NeighborhoodRow } from "../api";
import { matchNeighborhoods } from "../neighborhoods";

const MAX_SUGGESTIONS = 8;

interface NeighborhoodSearchProps {
  rows: NeighborhoodRow[];
  query: string;
  onQueryChange: (q: string) => void;
  onSelect: (slug: string) => void;
}

export function NeighborhoodSearch({ rows, query, onQueryChange, onSelect }: NeighborhoodSearchProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const matches = useMemo(() => matchNeighborhoods(rows, query), [rows, query]);
  const suggestions = query.trim() ? matches.slice(0, MAX_SUGGESTIONS) : [];
  const expanded = open && query.trim().length > 0;

  function choose(index: number) {
    const row = suggestions[index];
    if (!row) return;
    onSelect(row.slug);
    setOpen(false);
    setActive(-1);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!suggestions.length) return;
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((prev) => (prev + step + suggestions.length) % suggestions.length);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0) choose(active);
      else if (suggestions.length === 1) choose(0);
      return;
    }
    if (event.key === "Escape") {
      // first Escape closes and keeps the text; a second clears the filter
      if (expanded) setOpen(false);
      else onQueryChange("");
      setActive(-1);
      return;
    }
    if (event.key === "Tab") setOpen(false);
  }

  return (
    <div className="nb-search">
      <input
        ref={inputRef}
        type="search"
        className="nb-search-input"
        placeholder="Search neighborhoods…"
        aria-label="Search neighborhoods"
        role="combobox"
        aria-expanded={expanded}
        aria-controls="nb-listbox"
        aria-autocomplete="list"
        aria-activedescendant={expanded && active >= 0 ? `nb-opt-${active}` : undefined}
        value={query}
        onChange={(e) => {
          onQueryChange(e.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
      />
      {expanded && suggestions.length > 0 && (
        <ul className="nb-listbox" id="nb-listbox" role="listbox" aria-label="Neighborhood matches">
          {suggestions.map((row, i) => (
            <li
              key={row.slug}
              id={`nb-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "nb-option active" : "nb-option"}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(i)}
            >
              <span className="nb-option-name">{row.name}</span>
              <span className="nb-option-heat mono">{row.heat_max}</span>
            </li>
          ))}
        </ul>
      )}
      {expanded && suggestions.length === 0 && (
        <p className="muted nb-search-empty" role="status">
          No neighborhood matches “{query.trim()}”
        </p>
      )}
      <p className="muted nb-search-count" role="status" aria-live="polite">
        {query.trim() ? `${matches.length} of ${rows.length} neighborhoods` : `${rows.length} neighborhoods`}
      </p>
    </div>
  );
}
