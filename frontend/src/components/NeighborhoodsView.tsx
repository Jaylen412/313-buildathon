/**
 * Neighborhoods page: searchable, ranked list on the left; the selected
 * neighborhood's trend detail on the right. Block-level aggregates only, so
 * the page itself is public; the Summarize button inside the detail is gated.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, fetchNeighborhoods } from "../api";
import { NeighborhoodSearch } from "./NeighborhoodSearch";
import { NeighborhoodList } from "./NeighborhoodList";
import { matchNeighborhoods, sortRows, type SortKey } from "../neighborhoods";
import { NeighborhoodDetail } from "./NeighborhoodDetail";

interface NeighborhoodsViewProps {
  selectedSlug: string | null;
  onSelectSlug: (slug: string) => void;
  onOpenBlock: (geoid: string) => void;
}

export function NeighborhoodsView({ selectedSlug, onSelectSlug, onOpenBlock }: NeighborhoodsViewProps) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("heat_max");
  const list = useQuery({ queryKey: ["neighborhoods"], queryFn: fetchNeighborhoods });

  // stable identity: `?? []` would be a fresh array on every render
  const rows = useMemo(() => list.data?.neighborhoods ?? [], [list.data]);
  // one memo drives the list; the search popup filters the same rows, so the
  // two can never disagree about what matches
  const visible = useMemo(() => sortRows(matchNeighborhoods(rows, query), sort), [rows, query, sort]);

  const notScored = list.error instanceof ApiError && list.error.status === 503;

  return (
    <div className="nb-layout">
      <section className="nb-pane nb-pane-list" aria-label="Neighborhoods">
        <h2 className="nb-title">Neighborhoods</h2>
        <p className="muted nb-intro">
          Ranked by forecast investment pressure, rolled up from the block groups in each neighborhood.
        </p>
        {list.isLoading && (
          <div className="skeleton" aria-busy="true" aria-label="Loading neighborhoods">
            <div className="skeleton-line w80" />
            <div className="skeleton-line w60" />
            <div className="skeleton-line w80" />
          </div>
        )}
        {notScored && <p className="callout">{list.error instanceof ApiError ? list.error.message : ""}</p>}
        {list.isError && !notScored && (
          <p className="error">{(list.error as Error).message}</p>
        )}
        {list.data && (
          <>
            <NeighborhoodSearch
              rows={rows}
              query={query}
              onQueryChange={setQuery}
              onSelect={onSelectSlug}
            />
            <NeighborhoodList
              rows={visible}
              hotThreshold={list.data.hot_threshold}
              sort={sort}
              onSortChange={setSort}
              selectedSlug={selectedSlug}
              onSelect={onSelectSlug}
            />
          </>
        )}
      </section>
      <section className="nb-pane nb-pane-detail" aria-label="Neighborhood detail">
        {selectedSlug ? (
          <NeighborhoodDetail slug={selectedSlug} onOpenBlock={onOpenBlock} />
        ) : (
          <p className="muted nb-empty">Pick a neighborhood to see its trend and block groups.</p>
        )}
      </section>
    </div>
  );
}
