/**
 * Household exposure score -> ordinal risk category, for display only. The
 * underlying score stays a continuous, inspectable number (deterministic
 * scoring in code — CLAUDE.md "Non-negotiable design constraints"); this
 * just buckets it for the drawer so an organizer scans risk at a glance
 * instead of reading raw sums of weighted terms.
 *
 * Thresholds are grounded in the real score distribution across every
 * household in every hot block group (2026-09-18 pull, n=45,843; max score
 * is bounded ~11 by vulnerability.py's weights):
 *   p25 2.35, p50 3.84, p80 5.11, p95 7.25, p97 7.53.
 * "Critical" is set at the p95 line (~7% of households) so it reads as a
 * genuine special case, not just the top quartile.
 */
export type SeverityLevel = "low" | "moderate" | "high" | "critical";

export const SEVERITY_LABELS: Record<SeverityLevel, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  critical: "Critical",
};

export function severityOf(score: number): SeverityLevel {
  if (score >= 8.9) return "critical";
  if (score >= 7.8) return "high";
  if (score >= 6) return "moderate";
  return "low";
}
