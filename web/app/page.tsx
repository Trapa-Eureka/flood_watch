import { existsSync, readFileSync } from "fs";
import path from "path";
import supabaseServer from "@/lib/supabase-server";
import HomeDashboardMap, { type NationalStats, type Overlay, type RainfallLayer } from "./_components/HomeDashboardMap";

// 2026-08-29 home dashboard redesign — every number/layer here is real,
// RLS-scoped (session-aware client since Week 4-9 — see events/page.tsx's
// comment: a logged-out visitor still only sees completed+public events,
// same as before, but a logged-in viewer now sees every completed event on
// this page too, not just the public ones). No forecast/prediction layer:
// this pipeline only detects flooding from satellite imagery that has
// already arrived (see design-notes.md).
export const dynamic = "force-dynamic";

const TILES_ROOT = path.resolve(process.cwd(), "..", "data", "output", "tiles");

type AdminBoundaryRef = { name: string; level: string } | null;

// LibreWXR's public radar mosaic (real current rainfall — see
// design-notes.md "Week 4-5 rainfall overlay" for the original sourcing
// rationale, chosen over noah.up.edu.ph's own proprietary tiles because NOAH
// itself cites "JAXA Global Rainfall Watch (GSMaP) and DOST-PAGASA" as ITS
// source). Switched here from RainViewer (max zoom 7, global composite) to
// LibreWXR specifically for its PAGASA/DOST PANaHON 9-radar Philippines
// mosaic (2048x2048 grid over the whole archipelago, ~1km/px — a real,
// substantially finer source than a global product, still genuinely public
// per RA 8293 §176's government-works exception) served through a
// RainViewer-v2-API-compatible endpoint, max zoom 12. No API key, CORS-open,
// verified directly (curl + browser fetch) before switching. Still NOT
// barangay-precise — 1km/px is coarser than many barangays — the UI says so
// rather than implying more precision than the data has. Only radar.past is
// read, never radar.nowcast: this project shows no forecast/prediction
// layer anywhere (see Week4-5's original scope decision), so a short-range
// nowcast frame — which LibreWXR does offer, unlike RainViewer's free tier —
// is deliberately left unused.
// 2026-08-30: found live that a user's home-page load can hit this right as
// this same machine's Python pipeline is mid-download of a 900MB+ Sentinel-2
// composite (this is a single dev box serving both the Next app and the
// pipeline) — under that local network contention a 5s timeout genuinely
// wasn't enough and the whole rainfall section silently vanished with zero
// indication why. One retry with a longer timeout, not a longer single
// timeout, because a transient stall is more likely to clear in the time
// between two attempts than to still be blocking a single longer wait.
async function fetchRainfallLayer(attempt = 1): Promise<RainfallLayer> {
  try {
    const res = await fetch("https://api.librewxr.net/public/weather-maps.json", {
      signal: AbortSignal.timeout(8000),
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const past = data?.radar?.past;
    if (!Array.isArray(past) || past.length === 0) throw new Error("no radar.past frames in response");
    const latest = past[past.length - 1];
    return {
      tileUrlTemplate: `${data.host}${latest.path}/512/{z}/{x}/{y}/2/1_1.png`,
      frameTime: latest.time,
      maxZoom: 12,
    };
  } catch (err) {
    if (attempt < 2) return fetchRainfallLayer(attempt + 1);
    // Genuinely exhausted retries — omit the layer rather than block the
    // page or show something stale as if it were current (same convention
    // as every other external-service failure in this project: R2 upload,
    // style-load retry, etc.). HomeDashboardMap shows an honest
    // "unavailable" note for this rather than silently having no trace of
    // the section at all.
    console.error("fetchRainfallLayer: giving up after 2 attempts —", err);
    return null;
  }
}

export default async function Home() {
  const supabase = await supabaseServer();

  // Week 4-10 integration test found this live: before Week 4-9's client
  // swap, RLS alone was enough to guarantee "completed" here (anon could
  // never see anything else). A logged-in admin/viewer session now
  // legitimately sees registered/processing/failed rows too (RLS's own
  // events_select_admin/_viewer policies) — correct for /admin and /events,
  // but this dashboard was never meant to show pipeline-internal statuses,
  // only the same "what actually happened" summary regardless of who's
  // looking. Explicit .eq("status","completed") restores that, while still
  // letting a logged-in viewer see private-but-completed events (RLS still
  // decides visibility, this only decides status).
  const { data: events } = await supabase
    .from("events")
    .select("id, name, kind, post_event_date, created_at")
    .eq("status", "completed")
    .order("post_event_date", { ascending: false });

  // Flood overlay layers for the home map — reuses the exact Week4-4 local
  // tile bridge (data/output/tiles/{event_id}/flood_overlay_preview.png +
  // _bounds.json). Only events that actually have one get a layer; nothing
  // fabricated for events still missing it.
  const overlays: Overlay[] = (events ?? [])
    .map((e): Overlay | null => {
      const boundsPath = path.join(TILES_ROOT, e.id, "flood_overlay_bounds.json");
      const pngPath = path.join(TILES_ROOT, e.id, "flood_overlay_preview.png");
      if (!existsSync(boundsPath) || !existsSync(pngPath)) return null;
      const bounds = JSON.parse(readFileSync(boundsPath, "utf-8")).bounds_wgs84 as [number, number][];
      if (bounds.length !== 4) return null;
      return {
        id: e.id,
        name: e.name,
        kind: e.kind,
        postEventDate: e.post_event_date,
        overlayUrl: `/api/tiles/${e.id}/flood_overlay_preview.png`,
        bounds: bounds as Overlay["bounds"],
      };
    })
    .filter((o): o is Overlay => o !== null);

  // NOTE (Week3-9 lesson, re-applied here at national scale — see
  // events/[id]/page.tsx for the original per-event fix): exposure_stats
  // holds BOTH adm3_municipality and adm4_barangay rows — filtering to one
  // level before summing avoids double-counting the same flooded area.
  const { data: statsRaw } = await supabase
    .from("exposure_stats")
    .select("flooded_area_km2, flooded_area_pct, est_population_affected, est_buildings_affected, admin_boundaries(name, level)");

  const adm3Stats = (statsRaw ?? []).filter(
    (s) => (s.admin_boundaries as unknown as AdminBoundaryRef)?.level === "adm3_municipality",
  );
  const totalAreaKm2 = adm3Stats.reduce((sum, s) => sum + Number(s.flooded_area_km2), 0);
  const totalPopulation = adm3Stats.reduce((sum, s) => sum + (s.est_population_affected ?? 0), 0);
  const totalBuildings = adm3Stats.reduce((sum, s) => sum + (s.est_buildings_affected ?? 0), 0);
  const topRegions = adm3Stats
    .slice()
    .sort((a, b) => Number(b.flooded_area_km2) - Number(a.flooded_area_km2))
    .slice(0, 8)
    .map((s) => ({
      name: (s.admin_boundaries as unknown as AdminBoundaryRef)?.name ?? "?",
      floodedAreaKm2: Number(s.flooded_area_km2),
      floodedAreaPct: Number(s.flooded_area_pct),
    }));

  // "최근 갱신" = when the flood detection itself actually finished, not
  // when the event row was registered (Week4-3 found those can drift far
  // apart — the Kristine status bug was exactly that gap).
  const { data: latestExtent } = await supabase
    .from("flood_extents")
    .select("created_at")
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const nationalStats: NationalStats = {
    totalAreaKm2,
    totalPopulation,
    totalBuildings,
    topRegions,
    lastUpdated: latestExtent?.created_at ?? null,
    eventCount: events?.length ?? 0,
  };

  const rainfall = await fetchRainfallLayer();

  return <HomeDashboardMap overlays={overlays} nationalStats={nationalStats} rainfall={rainfall} />;
}
