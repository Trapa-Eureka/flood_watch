"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { createBaseMap } from "../../../_lib/maplibre-base";

const SOURCE_ID = "flood-overlay";
const LAYER_ID = "flood-overlay-layer";

// Same class-code -> color mapping as pipeline/tiles.py's FLOOD_CLASS_COLORS
// (kept in sync manually — this is a legend, not a re-derivation of the PNG).
const LEGEND = [
  { label: "New flooding", color: "rgba(217,45,32,0.85)" },
  { label: "Existing water (JRC permanent)", color: "rgba(49,109,204,0.65)" },
  { label: "Cloud-masked (unclassified)", color: "rgba(140,140,140,0.5)" },
];

type Corner = [number, number];

/** Renders pipeline/tiles.py's build_flood_overlay_png() output as a MapLibre
 * `image` source layer on top of the standard basemap — the flood classes
 * are placed by real WGS84 corner coordinates (`bounds`), not styled as a
 * generic <img>, so this is an actual georeferenced overlay, not just a
 * picture next to a map. Opacity is user-adjustable so the basemap (roads/
 * place names) stays checkable under the overlay. */
export default function FloodOverlayMap({
  overlayUrl,
  bounds,
}: {
  overlayUrl: string;
  bounds: [Corner, Corner, Corner, Corner];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [opacity, setOpacity] = useState(0.85);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const { map, cleanup } = createBaseMap(containerRef.current);
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      map.addSource(SOURCE_ID, { type: "image", url: overlayUrl, coordinates: bounds });
      map.addLayer({ id: LAYER_ID, type: "raster", source: SOURCE_ID, paint: { "raster-opacity": opacity } });

      const lngs = bounds.map((c) => c[0]);
      const lats = bounds.map((c) => c[1]);
      map.fitBounds(
        [
          [Math.min(...lngs), Math.min(...lats)],
          [Math.max(...lngs), Math.max(...lats)],
        ],
        { padding: 20, duration: 0 },
      );
    });

    return () => {
      cleanup();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlayUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer(LAYER_ID)) {
      map.setPaintProperty(LAYER_ID, "raster-opacity", opacity);
    }
  }, [opacity]);

  return (
    <div style={{ position: "relative" }}>
      <div
        ref={containerRef}
        style={{ width: "100%", aspectRatio: "4 / 3", borderRadius: 8, overflow: "hidden" }}
      />
      <div
        style={{
          position: "absolute",
          bottom: 8,
          left: 8,
          background: "rgba(255,255,255,0.92)",
          borderRadius: 6,
          padding: "8px 10px",
          fontSize: 11,
          display: "flex",
          flexDirection: "column",
          gap: 4,
          color: "#111",
        }}
      >
        {LEGEND.map((l) => (
          <div key={l.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 12, height: 12, borderRadius: 3, background: l.color, display: "inline-block", flexShrink: 0 }} />
            {l.label}
          </div>
        ))}
      </div>
      <div
        style={{
          position: "absolute",
          top: 8,
          left: 8,
          background: "rgba(255,255,255,0.92)",
          borderRadius: 6,
          padding: "6px 10px",
          fontSize: 11,
          display: "flex",
          alignItems: "center",
          gap: 6,
          color: "#111",
        }}
      >
        Opacity
        <input
          type="range"
          min={0.2}
          max={1}
          step={0.05}
          value={opacity}
          onChange={(e) => setOpacity(Number(e.target.value))}
        />
      </div>
    </div>
  );
}
