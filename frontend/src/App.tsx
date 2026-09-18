/**
 * Two-screen layout: heat map + block drawer. See md/architecture.md §3.
 */
import { useState } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { HeatMap, Legend } from "./components/HeatMap";
import { BlockDrawer } from "./components/BlockDrawer";
import { fetchBlocks } from "./api";
import "./App.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000 } } });

function Shell() {
  const [selectedGeoid, setSelectedGeoid] = useState<string | null>(null);
  const blocks = useQuery({ queryKey: ["blocks"], queryFn: fetchBlocks });
  const scored = blocks.data?.features.filter((f) => f.properties.heat_score != null).length ?? 0;
  const mode = blocks.data?.features.find((f) => f.properties.model_mode)?.properties.model_mode;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>Signals</h1>
          <p>Detroit anti-displacement early warning · block-group heat scores, public view</p>
        </div>
        {blocks.data && (
          <p className="muted">
            {scored} block groups scored · {mode === "fallback" ? "weighted index" : "forecast model"}
          </p>
        )}
      </header>
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
