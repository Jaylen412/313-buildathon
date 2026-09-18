/**
 * Selected block group: score, top signals, trend, households, brief button.
 * Households/brief are gated server-side by X-Org-Token; this component just
 * renders whatever the API returns (or a 403 message).
 */
import { useQuery } from "@tanstack/react-query";
import { fetchBlockDetail, fetchHouseholds } from "../api";
import { HouseholdList } from "./HouseholdList";
import { BriefPanel } from "./BriefPanel";

interface BlockDrawerProps {
  geoid: string;
  onClose: () => void;
}

export function BlockDrawer({ geoid, onClose }: BlockDrawerProps) {
  const detail = useQuery({
    queryKey: ["block", geoid],
    queryFn: () => fetchBlockDetail(geoid),
  });
  const households = useQuery({
    queryKey: ["households", geoid],
    queryFn: () => fetchHouseholds(geoid),
  });

  return (
    <aside className="block-drawer">
      <button type="button" className="close" onClick={onClose}>
        Close
      </button>
      {detail.isLoading && <p>Loading…</p>}
      {detail.isError && <p className="error">{(detail.error as Error).message}</p>}
      {detail.data && (
        <>
          <h2>{detail.data.neighborhood}</h2>
          <p className="heat-score">Heat score: {detail.data.heat_score}</p>
          <ul className="top-signals">
            {detail.data.top_signals.map((s) => (
              <li key={s.feature}>
                {s.feature} ({s.direction}, z={s.z.toFixed(2)})
              </li>
            ))}
          </ul>
          <p className="model-footnote">
            {detail.data.model_mode === "fallback"
              ? "weighted index (fallback)"
              : detail.data.backtest_summary ?? "model v1"}
          </p>
        </>
      )}

      <h3>Households</h3>
      {households.isError && <p className="error">{(households.error as Error).message}</p>}
      {households.data && <HouseholdList households={households.data} />}

      <BriefPanel geoid={geoid} />
    </aside>
  );
}
