/**
 * "Summarize" button + the rendered explanation.
 * POST /api/neighborhoods/{slug}/summary (gated). The server caches by slug +
 * model version, so a second click is instant and works offline; "Regenerate"
 * forces a fresh one. Same deliberate non-mutation shape as BriefPanel.
 *
 * This explains the metrics. It never recommends a program — that is the
 * outreach brief's job, and the backend prompt forbids it.
 */
import { useState } from "react";
import { ApiError, generateNeighborhoodSummary, type NeighborhoodSummaryResponse } from "../api";

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "Summaries are gated to organization accounts.";
    return err.message;
  }
  return String(err);
}

export function ExplainerPanel({ slug }: { slug: string }) {
  const [result, setResult] = useState<NeighborhoodSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate(force = false) {
    setLoading(true);
    setError(null);
    try {
      setResult(await generateNeighborhoodSummary(slug, force));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }

  const summary = result?.summary;
  return (
    <div className="brief-panel">
      <div className="brief-actions">
        <button type="button" onClick={() => handleGenerate(false)} disabled={loading}>
          {loading ? "Reading the numbers…" : summary ? "Show summary again" : "Summarize these metrics"}
        </button>
        {summary && (
          <button type="button" className="secondary" onClick={() => handleGenerate(true)} disabled={loading}>
            Regenerate
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {result && summary && (
        <article className="brief">
          <p className="muted brief-meta">
            {result.cached ? "Cached summary" : "Freshly written"} · {result.llm_model} · explains the
            numbers, does not compute them
          </p>
          <p className="nb-summary">{summary}</p>
        </article>
      )}
    </div>
  );
}
