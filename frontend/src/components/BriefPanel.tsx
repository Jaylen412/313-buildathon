/**
 * "Generate brief" button + rendered brief. Calls POST /api/blocks/{geoid}/brief.
 * Build order milestone: step 7 (Brief) = full demo.
 */
import { useState } from "react";
import { generateBrief, type Brief } from "../api";

interface BriefPanelProps {
  geoid: string;
}

export function BriefPanel({ geoid }: BriefPanelProps) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setLoading(true);
    setError(null);
    try {
      setBrief(await generateBrief(geoid));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="brief-panel">
      <button type="button" onClick={handleGenerate} disabled={loading}>
        {loading ? "Generating…" : "Generate brief"}
      </button>
      {error && <p className="error">{error}</p>}
      {brief && (
        <article>
          <h3>{brief.headline}</h3>
          <ul>
            {brief.what_is_changing.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p>{brief.why_it_matters}</p>
          <h4>Protections to offer</h4>
          <ul>
            {brief.protections_to_offer.map((p) => (
              <li key={p.name}>
                <strong>{p.name}</strong> — {p.who_qualifies} ({p.first_step})
              </li>
            ))}
          </ul>
          <h4>Canvassing plan</h4>
          <ol>
            {brief.canvassing_plan.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <p className="caveats">{brief.caveats.join(" ")}</p>
        </article>
      )}
    </div>
  );
}
