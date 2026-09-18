/**
 * Two-screen layout: heat map + block drawer. See md/architecture.md §3.
 */
import { useState } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { HeatMap } from "./components/HeatMap";
import { BlockDrawer } from "./components/BlockDrawer";
import { fetchBlocks } from "./api";
import "./App.css";

const queryClient = new QueryClient();

function Shell() {
  const [selectedGeoid, setSelectedGeoid] = useState<string | null>(null);
  const blocks = useQuery({ queryKey: ["blocks"], queryFn: fetchBlocks });

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Signals</h1>
        <p>Detroit anti-displacement early warning</p>
      </header>
      <main className="app-main">
        <div className="map-pane">
          {blocks.isError && (
            <p className="error">
              Could not load blocks: {(blocks.error as Error).message}
            </p>
          )}
          <HeatMap blocks={blocks.data} onSelect={setSelectedGeoid} />
        </div>
        {selectedGeoid && (
          <BlockDrawer geoid={selectedGeoid} onClose={() => setSelectedGeoid(null)} />
        )}
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
