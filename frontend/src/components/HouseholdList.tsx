/**
 * Ranked owner-occupied households on a hot block group. Every row shows
 * the reasons behind its score as chips; heirship is always labeled a
 * follow-up flag, never a determination (see CLAUDE.md "Non-negotiable
 * design constraints"). In demo mode the API has already stripped names and
 * parcel ids and reduced addresses to the hundred-block.
 */
import type { HouseholdsResponse } from "../api";

interface HouseholdListProps {
  data: HouseholdsResponse;
}

export function HouseholdList({ data }: HouseholdListProps) {
  if (!data.hot) {
    return (
      <p className="muted">
        Household ranking is only computed for hot block groups (heat score {data.hot_threshold}+). This one is
        below the threshold.
      </p>
    );
  }
  if (data.households.length === 0) {
    return <p className="muted">No owner-occupied residential parcels identified here.</p>;
  }
  const flagged = data.households.filter((h) => h.heirship_flag).length;
  return (
    <>
      <p className="muted household-summary">
        {data.households.length} owner-occupied households ranked by exposure
        {flagged > 0 && <> · {flagged} with a heirs'-property follow-up flag</>}
        {data.anonymized && <> · anonymized demo view</>}
      </p>
      <ol className="household-list">
        {data.households.map((h) => (
          <li key={h.parcel_id ?? `${h.rank}-${h.address}`}>
            <div className="household-row">
              <span className="household-rank">#{h.rank}</span>
              <span className="household-address">{h.address}</span>
              <span className="household-score" title="Exposure score (sum of weighted terms)">{h.score.toFixed(1)}</span>
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
        ))}
      </ol>
      <p className="muted household-footnote">{data.heirship_note}. Blight balance stands in for tax delinquency, which is not in any public layer.</p>
    </>
  );
}
