/**
 * One neighborhood: what is driving its score, the Summarize panel, the
 * aggregated trend (shown expanded — this page exists to display the trend),
 * and its block groups ranked most at risk first with a jump to the map.
 *
 * Signals are phrased as counts of block groups, never as a neighborhood
 * average: `mean_z` averages separate per-block-group comparisons against the
 * city, so it is not a statistic about the neighborhood. "mixed" means the
 * block groups disagree and is rendered as such rather than rounded to a side.
 */
import { useQuery } from "@tanstack/react-query";
import { ApiError, fetchNeighborhood, type AggregateSignal } from "../api";
import { heatColor, inkOn } from "../heat";
import { Trend } from "./Trend";
import { ExplainerPanel } from "./ExplainerPanel";

const DIRECTION_MARK: Record<AggregateSignal["direction"], string> = {
  up: "▲",
  down: "▼",
  mixed: "◆",
};

function describe(signal: AggregateSignal): string {
  const scope = `in ${signal.n_members} of ${signal.n_block_groups} block groups`;
  if (signal.direction === "mixed") {
    return `${signal.label} — mixed across block groups (${signal.n_up} above, ${signal.n_down} below the city)`;
  }
  const side = signal.direction === "up" ? "above" : "below";
  return `${signal.label} — ${side} the city, ${scope}`;
}

interface NeighborhoodDetailProps {
  slug: string;
  onOpenBlock: (geoid: string) => void;
}

export function NeighborhoodDetail({ slug, onOpenBlock }: NeighborhoodDetailProps) {
  const detail = useQuery({
    queryKey: ["neighborhood", slug],
    queryFn: () => fetchNeighborhood(slug),
  });

  if (detail.isLoading) {
    return (
      <div className="skeleton" aria-busy="true" aria-label="Loading neighborhood">
        <div className="skeleton-line w60" />
        <div className="skeleton-line w30" />
        <div className="skeleton-block" />
        <div className="skeleton-line" />
        <div className="skeleton-line w80" />
      </div>
    );
  }
  if (detail.isError) {
    const err = detail.error;
    return <p className="error">{err instanceof ApiError ? err.message : String(err)}</p>;
  }
  const data = detail.data;
  if (!data) return null;

  const lastYear = data.trend.years[data.trend.years.length - 1];

  return (
    <article className="nb-detail">
      <div className="drawer-head">
        <div>
          <h2>{data.name}</h2>
          <div className="muted nb-detail-sub">
            {data.n_hot} of {data.n_block_groups} block group{data.n_block_groups === 1 ? "" : "s"} at{" "}
            {data.hot_threshold}+ · average {data.heat_mean} · hottest {data.heat_max}
          </div>
        </div>
        <div
          className="heat-badge"
          style={{ background: heatColor(data.heat_max), color: inkOn(heatColor(data.heat_max)) }}
          title="Highest block-group score here: the city-wide percentile of predicted two-year price growth"
        >
          <span className="heat-badge-value">{data.heat_max}</span>
          <span className="heat-badge-label">pressure</span>
        </div>
      </div>

      {data.n_low_confidence > 0 && (
        <p className="callout">
          {data.n_low_confidence} of these block groups had fewer than 3 arm's-length sales in the scoring
          year. Treat their scores as hints, not findings.
        </p>
      )}

      <h3>What is driving it</h3>
      <ul className="signal-list">
        {data.top_signals.map((signal) => (
          <li key={signal.feature}>
            <span className={`signal-dir signal-dir-${signal.direction}`} aria-hidden="true">
              {DIRECTION_MARK[signal.direction]}
            </span>
            {describe(signal)}
          </li>
        ))}
      </ul>

      <ExplainerPanel slug={slug} />

      <h3>Trend, 2011–{lastYear}</h3>
      <p className="muted nb-trend-note">
        Counts summed across {data.n_block_groups} block group{data.n_block_groups === 1 ? "" : "s"};
        medians computed over every arm's-length sale in the neighborhood.
      </p>
      <Trend trend={data.trend} />

      <h3>Block groups, most at risk first</h3>
      <ol className="nb-members">
        {data.block_groups.map((member) => (
          <li key={member.bg_geoid}>
            <span
              className="nb-row-heat"
              style={{ background: heatColor(member.heat_score), color: inkOn(heatColor(member.heat_score)) }}
            >
              {member.heat_score}
            </span>
            <span className="nb-member-body">
              <span className="mono">{member.bg_geoid}</span>
              {member.confidence === "low" && <span className="chip">low confidence</span>}
              <span className="muted nb-member-signals">
                {member.top_signals.slice(0, 2).map((s) => s.label).join(" · ")}
              </span>
            </span>
            <button type="button" className="nb-member-open" onClick={() => onOpenBlock(member.bg_geoid)}>
              View on map →
            </button>
          </li>
        ))}
      </ol>

      <p className="model-footnote">{data.backtest_summary}</p>
      <p className="model-footnote">
        Neighborhoods are named by the most common parcel neighborhood in each block group, so their edges
        are approximate. The score ranks investment pressure; it does not measure displacement.
      </p>
    </article>
  );
}
