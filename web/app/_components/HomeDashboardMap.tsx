"use client";

import type { CSSProperties, ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { createBaseMap, PH_CENTER, PH_ZOOM } from "../_lib/maplibre-base";
import supabasePublic from "@/lib/supabase-public";

export type Overlay = {
  id: string;
  name: string;
  kind: string;
  postEventDate: string | null;
  overlayUrl: string;
  bounds: [[number, number], [number, number], [number, number], [number, number]];
};

export type TopRegion = { name: string; floodedAreaKm2: number; floodedAreaPct: number };

export type NationalStats = {
  totalAreaKm2: number;
  totalPopulation: number;
  totalBuildings: number;
  topRegions: TopRegion[];
  lastUpdated: string | null;
  eventCount: number;
};

// Server-fetched from api.librewxr.net (see fetchRainfallLayer in
// app/page.tsx) — null if that fetch failed, in which case this whole layer
// is simply omitted rather than shown broken or backfilled with a guess.
// maxZoom is the SOURCE's real native resolution ceiling (12, PAGASA's
// PANaHON mosaic) — passed as data rather than hardcoded here so a future
// source swap only touches page.tsx, not this component.
export type RainfallLayer = { tileUrlTemplate: string; frameTime: number; maxZoom: number } | null;

type SearchResult = { id: string; name: string; level: string; psgc_code: string; parent_name: string | null };
type RegionStat = {
  eventName: string;
  floodedAreaKm2: number;
  floodedAreaPct: number;
  estPopulationAffected: number | null;
  estBuildingsAffected: number | null;
};

// Same class-code -> color mapping as pipeline/tiles.py's FLOOD_CLASS_COLORS
// and events/[id]/_components/FloodOverlayMap.tsx — kept in sync manually.
const FLOOD_LEGEND = [
  { label: "New flooding", color: "#d92d20" },
  { label: "Existing water (JRC permanent)", color: "#316dcc" },
  { label: "Cloud-masked (unclassified)", color: "#8c8c8c" },
];

const LEVEL_LABEL: Record<string, string> = {
  adm3_municipality: "Municipality/City",
  adm4_barangay: "Barangay",
};

// 2026-08-30 visual-style pass (user feedback: "make the main screen look
// nicer, referencing the reference dashboards' presentation style" — scoped
// to styling only, see design-notes.md; no new data/metrics were added).
// Frosted-glass floating cards, consistent icon-badge accents per stat type,
// and a small brand mark — all cosmetic, every number underneath is
// unchanged from before this pass.
const ACCENT = { area: "#2563eb", population: "#7c3aed", buildings: "#b45309" };

const glassPanel: CSSProperties = {
  position: "fixed",
  zIndex: 10,
  background: "rgba(255,255,255,0.88)",
  backdropFilter: "blur(14px)",
  WebkitBackdropFilter: "blur(14px)",
  borderRadius: 14,
  border: "1px solid rgba(255,255,255,0.7)",
  boxShadow: "0 10px 30px rgba(15,23,42,0.16)",
} as CSSProperties;

const pillStyle: CSSProperties = {
  ...glassPanel,
  position: "static",
  display: "inline-flex",
  alignItems: "center",
  padding: "9px 16px",
  textDecoration: "none",
  color: "#111",
  fontSize: 13,
  fontWeight: 600,
};

const microLabel: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "#6b7280",
};

/** Recursively walks a GeoJSON Polygon/MultiPolygon coordinates array and
 * collects every [lon, lat] pair — enough to compute a bbox for fitBounds
 * without pulling in a turf dependency for one call site. */
function collectCoords(node: unknown, out: [number, number][]) {
  if (Array.isArray(node) && typeof node[0] === "number") {
    out.push(node as [number, number]);
    return;
  }
  if (Array.isArray(node)) node.forEach((child) => collectCoords(child, out));
}

/** Full-screen live flood-monitoring map for "/" (2026-08-29 redesign,
 * replaces the Week4-1 MapView scaffold). Everything shown is real:
 * - flood overlays = pipeline/tiles.py's actual per-event class rasters
 *   (Week4-4), never a predicted/forecast layer — this project's pipeline
 *   only detects flooding from satellite imagery that has already arrived,
 *   so there is no "expected extent" to show without inventing one.
 * - the rainfall layer is LibreWXR's PAGASA/DOST PANaHON radar mosaic (same
 *   underlying idea as noah.up.edu.ph's rainfall contours, which also cites
 *   PAGASA) — real current precipitation, not a forecast (radar.nowcast is
 *   deliberately never read, matching this page's no-prediction rule). Real
 *   resolution is ~1km/px, not barangay-precise — the panel says so.
 * - the stat panel copies image4's layout language (floating card, headline
 *   3-stat row, ranked list) but only for numbers this pipeline actually
 *   computes (exposure_stats) — deliberately omits Per Capita Income /
 *   Damage($) / risk-simulation panels since this project has no source of
 *   truth for any of those.
 */
export default function HomeDashboardMap({
  overlays,
  nationalStats,
  rainfall,
}: {
  overlays: Overlay[];
  nationalStats: NationalStats;
  rainfall: RainfallLayer;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selected, setSelected] = useState<SearchResult | null>(null);
  const [regionStats, setRegionStats] = useState<RegionStat[] | null>(null);
  const [showOverlays, setShowOverlays] = useState(true);
  const [showRainfall, setShowRainfall] = useState(true);
  // 2026-08-30: the server-side fetch in page.tsx succeeding proves nothing
  // about whether THIS browser can actually load the tile images — those are
  // fetched client-side, directly by the user's own browser, to
  // api.librewxr.net. Reported live: text panel showed real data, but no
  // colored overlay ever painted — exactly the signature of a client-side ad
  // blocker / privacy extension / network filter blocking that specific
  // domain while the server-side request (a different network path
  // entirely) goes through fine. This is a direct canary for that: a plain
  // client-side fetch to the same host, independent of MapLibre's own tile
  // loading, so a failure here is unambiguous evidence of client-side
  // blocking rather than a MapLibre rendering bug.
  const [clientRainfallBlocked, setClientRainfallBlocked] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!rainfall) return;
    fetch("https://api.librewxr.net/public/weather-maps.json", { mode: "cors", cache: "no-store" }).catch(() => {
      setClientRainfallBlocked(true);
    });
  }, [rainfall]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const { map, cleanup } = createBaseMap(containerRef.current);
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

    map.on("load", () => {
      // Rainfall goes in first (bottom of the stack) — flood extent is the
      // headline layer and should stay visually on top of it.
      if (rainfall) {
        map.addSource("rainfall", {
          type: "raster",
          tiles: [rainfall.tileUrlTemplate],
          tileSize: 512,
          maxzoom: rainfall.maxZoom, // real native resolution ceiling of the source (see fetchRainfallLayer in app/page.tsx) — no finer tiles exist past this
          attribution:
            'Weather data via <a href="https://librewxr.net/" target="_blank" rel="noopener">LibreWXR</a> — radar composite: PAGASA/DOST',
        });
        map.addLayer({
          id: "rainfall-layer",
          type: "raster",
          source: "rainfall",
          // Found by real testing (barangay search -> fitBounds zooms well
          // past the source's native resolution): past maxzoom, MapLibre's
          // default behavior is to upscale the last real tile to cover the
          // view — at deep enough zoom that's one pixel blown up dozens of
          // times, rendering as a giant blocky/smeared color patch that
          // looks broken, not just "lower resolution". Even this source's
          // real ~1km/px PAGASA grid has no barangay-level detail to show,
          // so fading out a couple zoom levels past its own maxzoom (rather
          // than lying with an upscaled blob) is the honest fix, not a
          // simplification. Layer maxzoom hard-stops rendering entirely
          // 2 levels past the source ceiling; the opacity ramp fades it out
          // smoothly on the way there instead of a jarring pop.
          maxzoom: rainfall.maxZoom + 2,
          paint: {
            "raster-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.6, rainfall.maxZoom, 0.6, rainfall.maxZoom + 2, 0],
          },
        });
      }

      overlays.forEach((o) => {
        const sourceId = `flood-${o.id}`;
        map.addSource(sourceId, { type: "image", url: o.overlayUrl, coordinates: o.bounds });
        map.addLayer({ id: `${sourceId}-layer`, type: "raster", source: sourceId, paint: { "raster-opacity": 0.85 } });
      });
      map.addSource("boundary-highlight", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "boundary-highlight-fill",
        type: "fill",
        source: "boundary-highlight",
        paint: { "fill-color": "#2563eb", "fill-opacity": 0.12 },
      });
      map.addLayer({
        id: "boundary-highlight-line",
        type: "line",
        source: "boundary-highlight",
        paint: { "line-color": "#2563eb", "line-width": 2 },
      });
    });

    // 2026-08-30: deliberately NOT using navigator.geolocation here — user
    // feedback was explicit that a location-permission prompt on load is
    // unwanted, full stop (not "make the denial state clearer", an earlier
    // misreading this session corrected). The PH-wide default view is the
    // only initial view now; the region/barangay search box is the intended
    // way to get to a specific area, not a browser permission popup.

    return () => {
      cleanup();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    overlays.forEach((o) => {
      const layerId = `flood-${o.id}-layer`;
      if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", showOverlays ? "visible" : "none");
    });
  }, [showOverlays, overlays]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer("rainfall-layer")) return;
    map.setLayoutProperty("rainfall-layer", "visibility", showRainfall ? "visible" : "none");
  }, [showRainfall]);

  const runSearch = useCallback((q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      const { data } = await supabasePublic().rpc("search_admin_boundaries", { q: q.trim(), p_limit: 8 });
      setResults((data as SearchResult[] | null) ?? []);
    }, 300);
  }, []);

  const selectResult = useCallback(async (r: SearchResult) => {
    setSelected(r);
    setResults([]);
    setQuery(r.name);
    setRegionStats(null);

    const map = mapRef.current;
    const { data: geo } = await supabasePublic().rpc("admin_boundary_geojson", { p_id: r.id });
    const row = (geo as { geojson: string }[] | null)?.[0];
    if (map && row?.geojson) {
      const geometry = JSON.parse(row.geojson);
      const source = map.getSource("boundary-highlight") as maplibregl.GeoJSONSource | undefined;
      source?.setData({ type: "Feature", properties: {}, geometry });

      const coords: [number, number][] = [];
      collectCoords(geometry.coordinates, coords);
      if (coords.length > 0) {
        const lngs = coords.map((c) => c[0]);
        const lats = coords.map((c) => c[1]);
        map.fitBounds(
          [
            [Math.min(...lngs), Math.min(...lats)],
            [Math.max(...lngs), Math.max(...lats)],
          ],
          { padding: 60, duration: 1000 },
        );
      }
    }

    const { data: stats } = await supabasePublic()
      .from("exposure_stats")
      .select("flooded_area_km2, flooded_area_pct, est_population_affected, est_buildings_affected, events(name)")
      .eq("admin_boundary_id", r.id);
    setRegionStats(
      (stats ?? []).map((s) => ({
        eventName: (s.events as unknown as { name: string } | null)?.name ?? "?",
        floodedAreaKm2: Number(s.flooded_area_km2),
        floodedAreaPct: Number(s.flooded_area_pct),
        estPopulationAffected: s.est_population_affected as number | null,
        estBuildingsAffected: s.est_buildings_affected as number | null,
      })),
    );
  }, []);

  const clearSelection = useCallback(() => {
    setSelected(null);
    setRegionStats(null);
    setQuery("");
    setResults([]);
    const map = mapRef.current;
    const source = map?.getSource("boundary-highlight") as maplibregl.GeoJSONSource | undefined;
    source?.setData({ type: "FeatureCollection", features: [] });
    map?.flyTo({ center: PH_CENTER, zoom: PH_ZOOM, duration: 1000 });
  }, []);

  return (
    <>
      <div id="map" ref={containerRef} />

      {/* brand mark + region search — top-left */}
      <div style={{ position: "fixed", top: 12, left: 12, zIndex: 10, width: 300, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ ...glassPanel, position: "static", display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 14px", alignSelf: "flex-start" }}>
          <IconWave size={16} color={ACCENT.area} />
          <span style={{ fontSize: 13, fontWeight: 700, color: "#111", letterSpacing: "0.01em" }}>PH Flood Watch</span>
        </div>
        <div>
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              runSearch(e.target.value);
            }}
            placeholder="Search region or barangay"
            style={{
              width: "100%",
              padding: "11px 14px",
              borderRadius: 12,
              border: "1px solid rgba(255,255,255,0.7)",
              background: "rgba(255,255,255,0.88)",
              backdropFilter: "blur(14px)",
              boxShadow: "0 10px 30px rgba(15,23,42,0.16)",
              fontSize: 14,
              boxSizing: "border-box",
              outline: "none",
            }}
          />
          {results.length > 0 && (
            <div style={{ ...glassPanel, position: "static", marginTop: 6, overflow: "hidden", borderRadius: 12 }}>
              {results.map((r) => (
                <button
                  key={r.id}
                  onClick={() => selectResult(r)}
                  style={{ display: "block", width: "100%", textAlign: "left", padding: "9px 14px", border: "none", background: "transparent", cursor: "pointer" }}
                >
                  <div style={{ fontWeight: 600, fontSize: 13, color: "#111" }}>{r.name}</div>
                  <div style={{ color: "#6b7280", fontSize: 11 }}>
                    {LEVEL_LABEL[r.level] ?? r.level}
                    {r.parent_name ? ` · ${r.parent_name}` : ""}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* nav — top-right */}
      <nav style={{ position: "fixed", top: 12, right: 12, zIndex: 10, display: "flex", gap: 8 }}>
        <Link href="/events" style={pillStyle}>
          View Events
        </Link>
        <Link href="/admin" style={pillStyle}>
          Admin
        </Link>
      </nav>

      {/* stat panel — bottom-left, national overview or the selected region */}
      <div style={{ ...glassPanel, bottom: 12, left: 12, width: 340, maxHeight: "62vh", overflowY: "auto", padding: 18 }}>
        {selected ? (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 16, color: "#111" }}>{selected.name}</div>
                <div style={{ ...microLabel, marginTop: 2 }}>
                  {LEVEL_LABEL[selected.level] ?? selected.level}
                  {selected.parent_name ? ` · ${selected.parent_name}` : ""}
                </div>
              </div>
              <button
                onClick={clearSelection}
                style={{ border: "none", background: "rgba(15,23,42,0.06)", borderRadius: 999, padding: "5px 10px", cursor: "pointer", color: "#374151", fontSize: 11, fontWeight: 600 }}
              >
                Show all ✕
              </button>
            </div>
            <div style={{ marginTop: 14 }}>
              {regionStats === null ? (
                <p style={{ fontSize: 12, color: "#9ca3af" }}>Loading...</p>
              ) : regionStats.length === 0 ? (
                <p style={{ fontSize: 12, color: "#9ca3af" }}>No flood data available for this region yet.</p>
              ) : (
                regionStats.map((s, i) => (
                  <div
                    key={i}
                    style={{
                      marginBottom: 10,
                      paddingBottom: 10,
                      borderBottom: i < regionStats.length - 1 ? "1px solid rgba(15,23,42,0.08)" : "none",
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#111", marginBottom: 4 }}>{s.eventName}</div>
                    <div style={{ fontSize: 12, color: "#4b5563" }}>
                      Flooded {s.floodedAreaKm2.toFixed(4)}km² ({s.floodedAreaPct.toFixed(2)}%)
                    </div>
                    <div style={{ fontSize: 12, color: "#4b5563" }}>
                      Population affected {s.estPopulationAffected?.toLocaleString() ?? "—"} · Buildings {s.estBuildingsAffected?.toLocaleString() ?? "—"}
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        ) : (
          <>
            <div style={{ fontWeight: 700, fontSize: 16, color: "#111", marginBottom: 14 }}>Nationwide Flood Status</div>
            <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
              <Stat icon={<IconDroplet size={15} color={ACCENT.area} />} accent={ACCENT.area} label="Flooded area" value={`${nationalStats.totalAreaKm2.toFixed(2)} km²`} />
              <Stat icon={<IconUsers size={15} color={ACCENT.population} />} accent={ACCENT.population} label="Population" value={nationalStats.totalPopulation.toLocaleString()} />
              <Stat icon={<IconHome size={15} color={ACCENT.buildings} />} accent={ACCENT.buildings} label="Buildings" value={nationalStats.totalBuildings.toLocaleString()} />
            </div>
            <div style={{ ...microLabel, marginBottom: 8 }}>Most affected regions</div>
            {nationalStats.topRegions.length === 0 ? (
              <p style={{ fontSize: 12, color: "#9ca3af" }}>No completed public events to show yet.</p>
            ) : (
              // key includes index: the same municipality can legitimately
              // appear twice (once per event that actually affected it, see
              // Rodriguez/Montalban in event2 + Kristine) — name alone isn't
              // unique, and merging the rows would hide that they're two
              // distinct real measurements, not one.
              nationalStats.topRegions.map((r, i) => (
                <div key={`${r.name}-${i}`} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <div
                    style={{
                      width: 18,
                      height: 18,
                      borderRadius: "50%",
                      background: i < 3 ? "rgba(217,45,32,0.12)" : "rgba(15,23,42,0.06)",
                      color: i < 3 ? "#d92d20" : "#6b7280",
                      fontSize: 10,
                      fontWeight: 700,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    {i + 1}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#1f2937" }}>
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
                      <span style={{ color: "#6b7280", flexShrink: 0, marginLeft: 8 }}>{r.floodedAreaKm2.toFixed(3)}km²</span>
                    </div>
                    <div style={{ height: 5, background: "rgba(15,23,42,0.07)", borderRadius: 999, marginTop: 4 }}>
                      <div
                        style={{
                          height: "100%",
                          width: `${Math.min(100, r.floodedAreaPct * 20)}%`,
                          background: "linear-gradient(90deg, #f59e0b, #d92d20)",
                          borderRadius: 999,
                        }}
                      />
                    </div>
                  </div>
                </div>
              ))
            )}
            <div style={{ marginTop: 14, fontSize: 11, color: "#9ca3af" }}>
              {nationalStats.eventCount} completed public event{nationalStats.eventCount === 1 ? "" : "s"}
              {nationalStats.lastUpdated && ` · Last updated ${new Date(nationalStats.lastUpdated).toLocaleString("en-PH")}`}
            </div>
          </>
        )}
      </div>

      {/* legend + layer toggles — bottom-right. Always shown (not gated on
          overlays.length>0 || rainfall) so a rainfall fetch failure still
          gets an honest "unavailable" line here instead of this whole panel
          — and any explanation of why — just vanishing (found live 2026-08-30:
          a silent LibreWXR fetch failure looked indistinguishable from a
          broken feature). */}
      <div style={{ ...glassPanel, bottom: 12, right: 12, padding: "12px 14px", fontSize: 11, width: 220 }}>
        <div style={{ marginBottom: overlays.length > 0 ? 12 : 0, paddingBottom: overlays.length > 0 ? 12 : 0, borderBottom: overlays.length > 0 ? "1px solid rgba(15,23,42,0.08)" : "none" }}>
          {rainfall ? (
            <>
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", color: "#111", fontWeight: 600, fontSize: 12 }}>
                <ToggleSwitch checked={showRainfall} onChange={setShowRainfall} />
                Current rainfall
              </label>
              <div style={{ color: "#9ca3af", marginTop: 6 }}>
                As of {new Date(rainfall.frameTime * 1000).toLocaleString("en-PH")} · PAGASA/DOST radar via{" "}
                <a href="https://librewxr.net/" target="_blank" rel="noopener noreferrer" style={{ color: "#6b7280" }}>
                  LibreWXR
                </a>
              </div>
              {/* Honest resolution note — the source is a real ~1km/px
                  national radar composite, genuinely finer than a global
                  mosaic, but still coarser than most individual barangays.
                  Saying so here beats implying precision the data doesn't
                  have. */}
              <div style={{ color: "#9ca3af", marginTop: 2 }}>~1km resolution, not barangay-precise</div>
              {clientRainfallBlocked && (
                <div style={{ color: "#b45309", marginTop: 6, fontWeight: 600 }}>
                  Your browser couldn&apos;t reach librewxr.net directly — an ad blocker or privacy extension may be blocking it. Data loaded server-side fine; try allow-listing this site.
                </div>
              )}
            </>
          ) : (
            <>
              <div style={{ color: "#111", fontWeight: 600, fontSize: 12 }}>Current rainfall</div>
              {/* Real, not a guess: page.tsx's fetchRainfallLayer() retried
                  once and still failed (LibreWXR is a small single-maintainer
                  service with no SLA, see design-notes.md) — say so instead
                  of leaving no trace this section ever existed. */}
              <div style={{ color: "#9ca3af", marginTop: 4 }}>Unavailable right now — reload to retry.</div>
            </>
          )}
        </div>
        {overlays.length > 0 && (
            <>
              <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, cursor: "pointer", color: "#111", fontWeight: 600, fontSize: 12 }}>
                <ToggleSwitch checked={showOverlays} onChange={setShowOverlays} />
                Show flood overlay
              </label>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                {FLOOD_LEGEND.map((l) => (
                  <div key={l.label} style={{ display: "flex", alignItems: "center", gap: 8, color: "#374151" }}>
                    <span style={{ width: 11, height: 11, borderRadius: 3, background: l.color, display: "inline-block", flexShrink: 0, boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.08)" }} />
                    {l.label}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
    </>
  );
}

function Stat({ icon, accent, label, value }: { icon: ReactNode; accent: string; label: string; value: string }) {
  return (
    <div style={{ flex: 1, minWidth: 0, background: "rgba(15,23,42,0.03)", borderRadius: 10, padding: "10px 8px", borderLeft: `3px solid ${accent}` }}>
      <div style={{ marginBottom: 4 }}>{icon}</div>
      {/* No nowrap/ellipsis here on purpose — this is a real measured
          number (never truncate it, even if a wider value than expected
          shows up someday; wrapping to a second line is always safe, a
          clipped "4.33 ..." reading like a placeholder is not). */}
      <div style={{ fontSize: 15, fontWeight: 800, color: "#111", lineHeight: 1.15, wordBreak: "break-word" }}>{value}</div>
      <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: "#6b7280", marginTop: 3 }}>{label}</div>
    </div>
  );
}

function ToggleSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <span
      role="switch"
      aria-checked={checked}
      onClick={(e) => {
        e.preventDefault();
        onChange(!checked);
      }}
      style={{
        display: "inline-flex",
        alignItems: "center",
        width: 30,
        height: 17,
        borderRadius: 999,
        background: checked ? "#2563eb" : "rgba(15,23,42,0.15)",
        padding: 2,
        cursor: "pointer",
        transition: "background 0.15s ease",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          width: 13,
          height: 13,
          borderRadius: "50%",
          background: "#fff",
          boxShadow: "0 1px 2px rgba(0,0,0,0.25)",
          transform: checked ? "translateX(13px)" : "translateX(0)",
          transition: "transform 0.15s ease",
        }}
      />
    </span>
  );
}

// Small inline icon set — no icon library dependency for four glyphs.
// currentColor-free (explicit `color` prop) so they work inside inline styles.
function IconWave({ size = 16, color = "#2563eb" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M2 17c1.5 1.5 3 1.5 4.5 0s3-1.5 4.5 0 3 1.5 4.5 0 3-1.5 4.5 0"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M2 12c1.5 1.5 3 1.5 4.5 0s3-1.5 4.5 0 3 1.5 4.5 0 3-1.5 4.5 0"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.55"
      />
    </svg>
  );
}

function IconDroplet({ size = 16, color = "#2563eb" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M12 2.5c3.5 4.6 7 8.9 7 12.7a7 7 0 1 1-14 0c0-3.8 3.5-8.1 7-12.7Z"
        fill={color}
      />
    </svg>
  );
}

function IconUsers({ size = 16, color = "#7c3aed" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="9" cy="8" r="3.2" fill={color} />
      <path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" stroke={color} strokeWidth="2" strokeLinecap="round" fill="none" />
      <circle cx="17" cy="9" r="2.4" fill={color} opacity="0.55" />
      <path d="M15.5 20c.3-2.9 1.9-4.9 4.5-5.4" stroke={color} strokeWidth="2" strokeLinecap="round" fill="none" opacity="0.55" />
    </svg>
  );
}

function IconHome({ size = 16, color = "#b45309" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M3 11.5 12 4l9 7.5" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.5 10v9.5a1 1 0 0 0 1 1H9v-6h6v6h2.5a1 1 0 0 0 1-1V10" stroke={color} strokeWidth="2" strokeLinejoin="round" fill="none" />
    </svg>
  );
}
