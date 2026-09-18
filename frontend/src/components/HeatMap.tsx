/**
 * Leaflet choropleth of scored block groups. CARTO Positron basemap (no API
 * key). Clicking a block group selects it for the drawer.
 *
 * Build order milestone: step 5 (API + map). Not yet wired to live data.
 */
import { MapContainer, TileLayer, GeoJSON } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { BlocksResponse } from "../api";

const DETROIT_CENTER: [number, number] = [42.3314, -83.0458];

interface HeatMapProps {
  blocks?: BlocksResponse;
  onSelect: (geoid: string) => void;
}

function colorForScore(score: number): string {
  // Low -> cool grey-blue, high -> warm red. Placeholder scale; swap for the
  // dataviz-skill sequential palette when the map ships.
  if (score >= 70) return "#d7301f";
  if (score >= 40) return "#fc8d59";
  return "#fee8c8";
}

export function HeatMap({ blocks, onSelect }: HeatMapProps) {
  return (
    <MapContainer center={DETROIT_CENTER} zoom={12} style={{ height: "100%", width: "100%" }}>
      <TileLayer
        url="https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://carto.com/attributions">CARTO</a>'
      />
      {blocks && (
        <GeoJSON
          data={blocks}
          style={(feature) => ({
            fillColor: colorForScore(feature?.properties.heat_score ?? 0),
            fillOpacity: 0.6,
            color: "#333",
            weight: 1,
          })}
          onEachFeature={(feature, layer) => {
            layer.on("click", () => onSelect(feature.properties.bg_geoid));
          }}
        />
      )}
    </MapContainer>
  );
}
