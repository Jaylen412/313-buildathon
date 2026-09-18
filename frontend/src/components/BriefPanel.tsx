/**
 * "Generate brief" button + rendered brief. POST /api/blocks/{geoid}/brief
 * (gated). The server caches briefs, so a second click is instant and
 * works offline; "Regenerate" forces a fresh one.
 */
import { useState } from "react";
import { ApiError, generateBrief, type BriefResponse } from "../api";

interface BriefPanelProps {
  geoid: string;
}

export function BriefPanel({ geoid }: BriefPanelProps) {
  const [result, setResult] = useState<BriefResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate(force = false) {
    setLoading(true);
    setError(null);
    try {
      setResult(await generateBrief(geoid, force));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const brief = result?.brief;
  return (
    <div className="brief-panel">
      <div className="brief-actions">
        <button type="button" onClick={() => handleGenerate(false)} disabled={loading}>
          {loading ? "Writing brief…" : brief ? "Show brief again" : "Generate outreach brief"}
        </button>
        {brief && (
          <button type="button" className="secondary" onClick={() => handleGenerate(true)} disabled={loading}>
            Regenerate
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {result && brief && (
        <article className="brief">
          <p className="muted brief-meta">
            {result.cached ? "Cached brief" : "Freshly written"} · {result.llm_model} · explains the score, does not compute it
          </p>
          <h3 className="brief-headline">{brief.headline}</h3>
          <h4>What is changing</h4>
          <ul>
            {brief.what_is_changing.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <h4>Why it matters here</h4>
          <p>{brief.why_it_matters}</p>
          <h4>Protections to offer first</h4>
          {brief.protections_to_offer.length === 0 ? (
            <p className="muted">None of the vetted protections apply to the counts in this summary.</p>
          ) : (
            <ul>
              {brief.protections_to_offer.map((p) => (
                <li key={p.name}>
                  <strong>{p.name}</strong> — {p.who_qualifies}
                  <div className="muted">First step: {p.first_step}</div>
                </li>
              ))}
            </ul>
          )}
          <h4>Canvassing plan</h4>
          <ol>
            {brief.canvassing_plan.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          {brief.caveats.length > 0 && (
            <>
              <h4>Caveats</h4>
              <ul className="caveats">
                {brief.caveats.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </>
          )}
        </article>
      )}
    </div>
  );
}
