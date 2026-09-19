/**
 * Ranked owner-occupied households on a hot block group. Every row shows
 * the reasons behind its score as chips; heirship is always labeled a
 * follow-up flag, never a determination (see CLAUDE.md "Non-negotiable
 * design constraints"). In demo mode the API has already stripped names and
 * parcel ids and reduced addresses to the hundred-block.
 *
 * Fetched 25 at a time (`HOUSEHOLDS_PAGE_SIZE`) via useInfiniteQuery; a
 * sentinel <li> at the bottom of the list is watched with an
 * IntersectionObserver, so scrolling near the end triggers the next page.
 */
import { useEffect, useRef } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { ApiError, fetchHouseholds, HOUSEHOLDS_PAGE_SIZE } from "../api";
import { severityOf, SEVERITY_LABELS } from "../severity";

interface HouseholdListProps {
  geoid: string;
}

function statusMessage(err: unknown): { text: string; pending: boolean } {
  if (err instanceof ApiError) {
    if (err.status === 501) return { text: err.message, pending: true };
    if (err.status === 403) return { text: "Household data is gated to organization accounts.", pending: false };
    return { text: err.message, pending: false };
  }
  return { text: String(err), pending: false };
}

export function HouseholdList({ geoid }: HouseholdListProps) {
  const query = useInfiniteQuery({
    queryKey: ["households", geoid],
    queryFn: ({ pageParam }) => fetchHouseholds(geoid, pageParam, HOUSEHOLDS_PAGE_SIZE),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.offset + lastPage.households.length : undefined),
    retry: false,
  });

  const sentinelRef = useRef<HTMLLIElement | null>(null);
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = query;
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !isFetchingNextPage) fetchNextPage();
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  if (query.isLoading) return <p className="muted">Ranking owner-occupied households…</p>;
  if (query.isError) {
    const { text, pending } = statusMessage(query.error);
    return <p className={pending ? "muted" : "error"}>{text}</p>;
  }

  const first = query.data!.pages[0];
  if (!first.hot) {
    return (
      <p className="muted">
        Household ranking is only computed for hot block groups (heat score {first.hot_threshold}+). This one is
        below the threshold.
      </p>
    );
  }
  const households = query.data!.pages.flatMap((p) => p.households);
  if (households.length === 0) {
    return <p className="muted">No owner-occupied residential parcels identified here.</p>;
  }
  const flagged = households.filter((h) => h.heirship_flag).length;
  const critical = households.filter((h) => severityOf(h.score) === "critical").length;
  const total = first.total;
  return (
    <>
      <p className="muted household-summary">
        Showing {households.length} of {total} owner-occupied households, ranked by exposure
        {critical > 0 && <> · {critical} critical</>}
        {flagged > 0 && <> · {flagged} with a heirs'-property follow-up flag</>}
        {first.anonymized && <> · anonymized demo view</>}
      </p>
      <ol className="household-list">
        {households.map((h) => {
          const level = severityOf(h.score);
          return (
            <li key={h.parcel_id ?? `${h.rank}-${h.address}`}>
              <div className="household-row">
                <span className="household-rank">#{h.rank}</span>
                <span className="household-address">{h.address}</span>
                <span
                  className={`household-score household-score-${level}`}
                  title={`Exposure score ${h.score.toFixed(1)} (sum of weighted terms)`}
                >
                  {SEVERITY_LABELS[level]}
                </span>
              </div>
              {h.owner && <div className="muted household-owner">{h.owner}</div>}
              <div className="household-reasons">
                {h.reasons.map((reason) => (
                  <span className={reason.startsWith("Possible heirs") ? "chip chip-flag" : "chip"} key={reason} title={reason}>
                    {reason}
                  </span>
                ))}
              </div>
            </li>
          );
        })}
        {hasNextPage && (
          <li ref={sentinelRef} className="household-load-more muted" aria-hidden="true">
            {isFetchingNextPage ? "Loading more…" : ""}
          </li>
        )}
      </ol>
      <p className="muted household-footnote">{first.heirship_note}. Blight balance stands in for tax delinquency, which is not in any public layer.</p>
    </>
  );
}
