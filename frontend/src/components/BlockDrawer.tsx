/**
 * Selected block group: score, top signals in plain language, per-year
 * trend, households (gated) and the brief button. Households/brief are
 * gated server-side by X-Org-Token; a 501 means that build step isn't in
 * yet and is shown as such, not as an error.
 */
import { useQuery } from "@tanstack/react-query";
import { ApiError, fetchBlockDetail, fetchHouseholds, type TopSignal } from "../api";
import { heatColor, inkOn } from "../heat";
import { HouseholdList } from "./HouseholdList";
import { BriefPanel } from "./BriefPanel";
import { Trend } from "./Trend";

interface BlockDrawerProps {
  geoid: string;
  onClose: () => void;
}

function describe(s: TopSignal): string {
  const magnitude = Math.abs(s.z) >= 2 ? "far" : Math.abs(s.z) >= 1 ? "well" : "slightly";
  const dir = s.direction === "up" ? "above" : "below";
  return `${s.label} — ${magnitude} ${dir} the city that year`;
}

function statusMessage(err: unknown): { text: string; pending: boolean } {
  if (err instanceof ApiError) {
    if (err.status === 501) return { text: err.message, pending: true };
    if (err.status === 403) return { text: "Household data is gated to organization accounts.", pending: false };
    return { text: err.message, pending: false };
  }
  return { text: String(err), pending: false };
}

export function BlockDrawer({ geoid, onClose }: BlockDrawerProps) {
  const detail = useQuery({ queryKey: ["block", geoid], queryFn: () => fetchBlockDetail(geoid) });
  const households = useQuery({
    queryKey: ["households", geoid],
    queryFn: () => fetchHouseholds(geoid),
    retry: false,
  });

  return (
    <aside className="block-drawer" aria-label="Block group details">
      <button type="button" className="close" onClick={onClose} aria-label="Close">×</button>

      {detail.isLoading && <p className="muted">Loading…</p>}
      {detail.isError && <p className="error">{(detail.error as Error).message}</p>}
      {detail.data && (
        <>
          <div className="drawer-head">
            <div>
              <h2>{detail.data.neighborhood ?? "Block group"}</h2>
              <div className="muted mono">block group {detail.data.bg_geoid}</div>
            </div>
            <div
              className="heat-badge"
              style={{ background: heatColor(detail.data.heat_score), color: inkOn(heatColor(detail.data.heat_score)) }}
              title="City-wide percentile of predicted two-year price growth"
            >
              <span className="heat-badge-value">{detail.data.heat_score}</span>
              <span className="heat-badge-label">heat</span>
            </div>
          </div>

          {detail.data.confidence === "low" && (
            <p className="callout">
              Low confidence: fewer than 3 arm's-length sales here in the scoring year. Treat this score as a
              hint, not a finding.
            </p>
          )}

          <h3>Why this score</h3>
          <ul className="signal-list">
            {detail.data.top_signals.map((s) => (
              <li key={s.feature}>
                <span className={`signal-dir signal-dir-${s.direction}`} aria-hidden="true">
                  {s.direction === "up" ? "▲" : "▼"}
                </span>
                {describe(s)}
              </li>
            ))}
          </ul>

          <p className="model-footnote">{detail.data.backtest_summary}</p>
        </>
      )}

      <h3>Households to reach first</h3>
      {households.isLoading && <p className="muted">Loading…</p>}
      {households.isError && (
        <p className={statusMessage(households.error).pending ? "muted" : "error"}>
          {statusMessage(households.error).text}
        </p>
      )}
      {households.data && <HouseholdList data={households.data} />}

      <BriefPanel geoid={geoid} />

      {detail.data && (
        <details className="trend-details">
          <summary>
            <h3>Trend, 2011–{detail.data.trend.years[detail.data.trend.years.length - 1]}</h3>
          </summary>
          <Trend trend={detail.data.trend} />
        </details>
      )}
    </aside>
  );
}
