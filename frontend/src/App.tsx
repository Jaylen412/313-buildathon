/**
 * Two-screen layout: heat map + block drawer. See md/architecture.md §3.
 */
import { useState } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { HeatMap, Legend } from "./components/HeatMap";
import { BlockDrawer } from "./components/BlockDrawer";
import { Sidebar } from "./components/Sidebar";
import { PlaceholderView } from "./components/PlaceholderView";
import { ApiError, fetchBlocks, fetchHealth } from "./api";
import "./App.css";

export type ViewName = "home" | "map" | "residents" | "insights" | "settings";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000 } } });

function Shell() {
  const [activeView, setActiveView] = useState<ViewName>("map");
  const [selectedGeoid, setSelectedGeoid] = useState<string | null>(null);
  const blocks = useQuery({ queryKey: ["blocks"], queryFn: fetchBlocks });
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 30_000, retry: 1 });
  const scored = blocks.data?.features.filter((f) => f.properties.heat_score != null).length ?? 0;
  const mode = blocks.data?.features.find((f) => f.properties.model_mode)?.properties.model_mode;
  const offline = health.isError;
  const notScored = blocks.isError && blocks.error instanceof ApiError && blocks.error.status === 503;

  return (
    <div className="app-shell">
      <div className="app-body">
        <Sidebar active={activeView} onChange={setActiveView} />
        <div className="app-content">
          <header className="app-header">
            <div>
              <h1>Signals</h1>
              <p>Detroit anti-displacement early warning</p>
            </div>
            {blocks.data && (
              <p className="muted">
                {scored} block groups scored | {mode === "fallback" ? "weighted index" : "forecast model"}
              </p>
            )}
          </header>
          {offline && (
            <div className="banner error">
              API is not reachable at {import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000"}. Start it with{" "}
              <code>cd backend && uv run signals serve</code>.
            </div>
          )}
          {!offline && notScored && (
            <div className="banner">
              Data isn't scored yet. Run <code>uv run signals ingest</code>, <code>features</code>, then <code>train</code> in{" "}
              <code>backend/</code> (see README).
            </div>
          )}
          {activeView === "map" && (
            <main className="app-main">
              <div className="map-pane">
                {blocks.isLoading && <p className="map-status">Loading block groups…</p>}
                {blocks.isError && (
                  <p className="map-status error">Could not load blocks: {(blocks.error as Error).message}</p>
                )}
                <HeatMap blocks={blocks.data} selectedGeoid={selectedGeoid} onSelect={setSelectedGeoid} />
                <Legend />
              </div>
              {selectedGeoid && <BlockDrawer geoid={selectedGeoid} onClose={() => setSelectedGeoid(null)} />}
            </main>
          )}
          {activeView === "home" && (
            <PlaceholderView title="Home" description="A dashboard overview of Detroit displacement risk is coming soon." />
          )}
          {activeView === "residents" && (
            <PlaceholderView
              title="Residents"
              description="Household-level search and detail across all block groups is coming soon."
            />
          )}
          {activeView === "insights" && (
            <PlaceholderView title="Insights" description="City-wide trends and model insights are coming soon." />
          )}
          {activeView === "settings" && (
            <PlaceholderView title="Settings" description="Preferences and account settings are coming soon." />
          )}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Shell />
    </QueryClientProvider>
  );
}
