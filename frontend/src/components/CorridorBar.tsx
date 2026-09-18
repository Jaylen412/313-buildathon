/**
 * Demo fly-to presets (backend demo.py, md/TODO.md D.1). Selecting one
 * behaves exactly like clicking the block group on the map.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchCorridors } from "../api";

interface CorridorBarProps {
  selectedGeoid: string | null;
  onSelect: (geoid: string) => void;
}

export function CorridorBar({ selectedGeoid, onSelect }: CorridorBarProps) {
  const corridors = useQuery({ queryKey: ["corridors"], queryFn: fetchCorridors });
  if (!corridors.data?.length) return null;
  const suggested = corridors.data.some((c) => c.suggested);
  return (
    <div className="corridor-bar" role="group" aria-label="Demo corridors">
      <span className="muted corridor-bar-label">Demo{suggested ? " (suggested picks)" : ""}:</span>
      {corridors.data.map((c) => (
        <button
          type="button"
          key={c.key}
          className={c.bg_geoid === selectedGeoid ? "corridor-btn active" : "corridor-btn"}
          onClick={() => onSelect(c.bg_geoid)}
          title={c.why}
        >
          {c.label}
          {c.heat_score != null && <span className="corridor-heat">{c.heat_score}</span>}
        </button>
      ))}
    </div>
  );
}
