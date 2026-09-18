/**
 * Small-multiple sparklines for a block group's per-year series. One series
 * per chart (so no legend; the title names it), 2px line, 8px markers with
 * a hover title, the partial current year drawn hollow, baseline at zero.
 */
import type { Trend as TrendData } from "../api";

const METRICS: { key: string; title: string; format: (v: number) => string }[] = [
  { key: "median_ppsf", title: "Median $/sq ft (arm's-length sales)", format: (v) => `$${v.toFixed(0)}` },
  { key: "n_sales", title: "Arm's-length sales", format: (v) => v.toFixed(0) },
  { key: "llc_share", title: "Share of sales to LLCs", format: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "permit_count", title: "Building permits", format: (v) => v.toFixed(0) },
  { key: "blight_tickets", title: "Blight tickets", format: (v) => v.toFixed(0) },
];

const W = 300;
const H = 64;
const PAD = { l: 6, r: 6, t: 8, b: 16 };

function Sparkline({ years, values, partialYear, format }: {
  years: number[];
  values: (number | null)[];
  partialYear: number | null;
  format: (v: number) => string;
}) {
  const pts = years
    .map((y, i) => ({ y, v: values[i] }))
    .filter((p): p is { y: number; v: number } => p.v != null);
  if (pts.length < 2) return <div className="trend-empty">not enough data</div>;

  const x = (year: number) =>
    PAD.l + ((year - years[0]) / Math.max(1, years[years.length - 1] - years[0])) * (W - PAD.l - PAD.r);
  const max = Math.max(...pts.map((p) => p.v));
  const yScale = (v: number) => PAD.t + (1 - (max === 0 ? 0 : v / max)) * (H - PAD.t - PAD.b);
  const path = pts.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.y).toFixed(1)},${yScale(p.v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  const first = pts[0];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="trend-svg" role="img">
      <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} className="trend-baseline" />
      <path d={path} className="trend-line" />
      {pts.map((p) => (
        <circle
          key={p.y}
          cx={x(p.y)}
          cy={yScale(p.v)}
          r={4}
          className={p.y === partialYear ? "trend-marker trend-marker-partial" : "trend-marker"}
        >
          <title>{`${p.y}${p.y === partialYear ? " (partial year)" : ""}: ${format(p.v)}`}</title>
        </circle>
      ))}
      <text x={x(first.y)} y={H - 3} className="trend-axis" textAnchor="start">{first.y}</text>
      <text x={x(last.y)} y={H - 3} className="trend-axis" textAnchor="end">{last.y}</text>
      <text x={W - PAD.r} y={PAD.t + 4} className="trend-value" textAnchor="end">{format(last.v)}</text>
    </svg>
  );
}

export function Trend({ trend }: { trend: TrendData }) {
  if (!trend.years.length) return null;
  return (
    <div className="trend-grid">
      {METRICS.map((m) =>
        trend.series[m.key] ? (
          <div key={m.key} className="trend-card">
            <div className="trend-title">{m.title}</div>
            <Sparkline years={trend.years} values={trend.series[m.key]} partialYear={trend.partial_year} format={m.format} />
          </div>
        ) : null,
      )}
    </div>
  );
}
