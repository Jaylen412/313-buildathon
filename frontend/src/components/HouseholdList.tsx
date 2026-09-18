/**
 * Ranked owner-occupied households on a hot block group. Reasons render as
 * chips; heirship is always labeled a follow-up flag, never a determination
 * (see md/CLAUDE.md "Non-negotiable design constraints").
 *
 * Build order milestone: step 6 (Vulnerability).
 */
import type { Household } from "../api";

interface HouseholdListProps {
  households: Household[];
}

export function HouseholdList({ households }: HouseholdListProps) {
  if (households.length === 0) {
    return <p>No households loaded yet.</p>;
  }
  return (
    <ol className="household-list">
      {households.map((h, i) => (
        <li key={h.parcel_id ?? i}>
          <div className="household-address">{h.address}</div>
          <div className="household-reasons">
            {h.reasons.map((reason) => (
              <span className="chip" key={reason}>
                {reason}
              </span>
            ))}
            {h.heirship_flag && (
              <span className="chip chip-flag" title="Follow-up flag, not a determination">
                Possible heirs' property — follow up
              </span>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
