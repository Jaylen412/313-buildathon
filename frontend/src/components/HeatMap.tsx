/**
 * Leaflet choropleth of scored block groups. Esri dark-gray canvas basemap
 * (no API key). Hover shows neighborhood + score; click selects for the drawer.
 * Low-confidence block groups (< 3 sales in the scoring year) draw with a
 * dashed border so the map never over-claims.
 */
import { useEffect, useMemo, useRef } from "react";
import { MapContainer, TileLayer, GeoJSON, useMap } from "react-leaflet";
import type { Layer, PathOptions } from "leaflet";
import type { Feature } from "geojson";
import "leaflet/dist/leaflet.css";
import type { BlockFeature, BlocksResponse } from "../api";
import { heatColor, HEAT_STEPS, NO_SCORE_HEX } from "../heat";

const DETROIT_CENTER: [number, number] = [42.36, -83.08];

interface HeatMapProps {
  blocks?: BlocksResponse;
  selectedGeoid: string | null;
  onSelect: (geoid: string) => void;
}

function styleFor(feature: BlockFeature, selected: boolean): PathOptions {
  const p = feature.properties;
  return {
    fillColor: heatColor(p.heat_score),
    fillOpacity: p.heat_score == null ? 0.35 : 0.72,
    color: selected ? "#ffffff" : "#5b5a54",
    weight: selected ? 2.5 : 0.6,
    dashArray: p.confidence === "low" ? "3 3" : undefined,
  };
}

function FlyToSelected({ blocks, geoid }: { blocks?: BlocksResponse; geoid: string | null }) {
  const map = useMap();
  useEffect(() => {
    if (!blocks || !geoid) return;
    const f = blocks.features.find((x) => x.properties.bg_geoid === geoid);
    if (!f || f.geometry.type !== "Polygon" && f.geometry.type !== "MultiPolygon") return;
    const coords = (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates)
      .flat(2) as unknown as [number, number][];
    const lats = coords.map((c) => c[1]);
    const lons = coords.map((c) => c[0]);
    map.fitBounds(
      [
        [Math.min(...lats), Math.min(...lons)],
        [Math.max(...lats), Math.max(...lons)],
      ],
      { maxZoom: 15, padding: [40, 40] },
    );
  }, [blocks, geoid, map]);
  return null;
}

export function Legend() {
  return (
    <div className="map-legend" aria-label="Heat score legend">
      <div className="map-legend-title">Investment pressure (heat score)</div>
      <div className="map-legend-ramp">
        {HEAT_STEPS.map((s, i) => (
          <div key={s.hex} className="map-legend-step">
            <span className="map-legend-swatch" style={{ background: s.hex }} />
            <span className="map-legend-label">
              {i === HEAT_STEPS.length - 1 ? `${s.min}+` : `${s.min}–${HEAT_STEPS[i + 1].min - 1}`}
            </span>
          </div>
        ))}
      </div>
      <div className="map-legend-notes">
        <span><span className="map-legend-swatch" style={{ background: NO_SCORE_HEX }} /> no score</span>
        <span><span className="map-legend-swatch map-legend-dashed" /> low confidence (&lt;3 sales)</span>
      </div>
    </div>
  );
}

export function HeatMap({ blocks, selectedGeoid, onSelect }: HeatMapProps) {
  const layerRef = useRef<import("leaflet").GeoJSON | null>(null);
  // Re-style in place on selection change instead of remounting 625 polygons.
  useEffect(() => {
    layerRef.current?.eachLayer((layer) => {
      const f = (layer as Layer & { feature?: BlockFeature }).feature;
      if (f) (layer as import("leaflet").Path).setStyle(styleFor(f, f.properties.bg_geoid === selectedGeoid));
    });
  }, [selectedGeoid]);

  const data = useMemo(() => blocks, [blocks]);

  return (
    <MapContainer center={DETROIT_CENTER} zoom={11.5} style={{ height: "100%", width: "100%" }} preferCanvas>
      {/* Esri's dark-gray canvas: keyless, same service tier as the light-gray
          base this replaced. CARTO's basemaps now watermark "API KEY REQUIRED"
          without a key. */}
      <TileLayer
        url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        attribution="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
        maxZoom={16}
      />
      {data && (
        <GeoJSON
          ref={layerRef}
          data={data}
          style={(feature) => styleFor(feature as BlockFeature, (feature as BlockFeature).properties.bg_geoid === selectedGeoid)}
          onEachFeature={(feature: Feature, layer: Layer) => {
            const p = (feature as BlockFeature).properties;
            const score = p.heat_score == null ? "no score" : `heat ${p.heat_score}`;
            const conf = p.confidence === "low" ? " · low confidence" : "";
            layer.bindTooltip(`<strong>${p.neighborhood ?? p.bg_geoid}</strong><br/>${score}${conf}`, {
              sticky: true,
              direction: "top",
              className: "map-tooltip",
            });
            layer.on("click", () => onSelect(p.bg_geoid));
          }}
        />
      )}
      <FlyToSelected blocks={data} geoid={selectedGeoid} />
    </MapContainer>
  );
}
