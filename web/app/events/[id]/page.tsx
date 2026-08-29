import { existsSync, readFileSync } from "fs";
import path from "path";
import { notFound } from "next/navigation";
import supabasePublic from "@/lib/supabase-public";
import BeforeAfterSlider from "./_components/BeforeAfterSlider";
import FloodOverlayMap from "./_components/FloodOverlayMap";

export const dynamic = "force-dynamic";

const TILES_ROOT = path.resolve(process.cwd(), "..", "data", "output", "tiles");

type AoiRef = { name: string } | null;
type AdminBoundaryRef = { name: string; level: string } | null;

export default async function EventDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = supabasePublic();

  const { data: event, error: eventError } = await supabase
    .from("events")
    .select("id, name, kind, pre_event_date, post_event_date, aois(name)")
    .eq("id", id)
    .single();

  if (eventError || !event) notFound();

  // NOTE (Week 3-9 lesson, see docs/design-notes.md): exposure_stats holds
  // BOTH adm3_municipality and adm4_barangay rows per event — summing across
  // both levels double-counts the same flooded area/population. Filtering to
  // one level (adm3_municipality) here is not optional cleanup, it's the fix
  // for a real bug this project already hit once.
  const { data: statsRaw } = await supabase
    .from("exposure_stats")
    .select("flooded_area_km2, flooded_area_pct, est_population_affected, est_buildings_affected, admin_boundaries(name, level)")
    .eq("event_id", id);

  const adm3Stats = (statsRaw ?? []).filter(
    (s) => (s.admin_boundaries as unknown as AdminBoundaryRef)?.level === "adm3_municipality",
  );
  const totalAreaKm2 = adm3Stats.reduce((sum, s) => sum + Number(s.flooded_area_km2), 0);
  const totalPop = adm3Stats.reduce((sum, s) => sum + (s.est_population_affected ?? 0), 0);
  const totalBuildings = adm3Stats.reduce((sum, s) => sum + (s.est_buildings_affected ?? 0), 0);

  const hasPre = existsSync(path.join(TILES_ROOT, id, "pre_rgb_preview.jpg"));
  const hasPost = existsSync(path.join(TILES_ROOT, id, "post_rgb_preview.jpg"));

  // Week 4-4: flood overlay map. bounds_wgs84 is read straight off the
  // filesystem sidecar pipeline/tiles.py wrote (same local-bridge pattern as
  // the pre/post previews above — no DB column for this, it's a rendering
  // detail of a file that already lives under data/output/tiles/).
  const overlayPngPath = path.join(TILES_ROOT, id, "flood_overlay_preview.png");
  const overlayBoundsPath = path.join(TILES_ROOT, id, "flood_overlay_bounds.json");
  const hasFloodOverlay = existsSync(overlayPngPath) && existsSync(overlayBoundsPath);
  const floodOverlayBounds = hasFloodOverlay
    ? (JSON.parse(readFileSync(overlayBoundsPath, "utf-8")).bounds_wgs84 as [number, number][])
    : null;

  const aoiName = (event.aois as unknown as AoiRef)?.name ?? "AOI 없음";

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px", display: "flex", flexDirection: "column", gap: 24 }}>
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 600 }}>{event.name}</h1>
        <p style={{ fontSize: 13, color: "#666", marginTop: 4 }}>
          {aoiName} · {event.pre_event_date} → {event.post_event_date ?? "진행중"}
        </p>
      </div>

      <section>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>전후 비교</h2>
        {hasPost ? (
          <BeforeAfterSlider
            beforeSrc={hasPre ? `/api/tiles/${id}/pre_rgb_preview.jpg` : null}
            afterSrc={`/api/tiles/${id}/post_rgb_preview.jpg`}
          />
        ) : (
          <p style={{ color: "#666" }}>이 이벤트는 아직 타일이 생성되지 않았습니다.</p>
        )}
        {hasPost && (
          // spec.md §13's standing rule — every map/report showing Sentinel
          // imagery carries this, not just the final PDF report (Week 4-6).
          <p style={{ fontSize: 11, color: "#999", marginTop: 4 }}>
            Contains modified Copernicus Sentinel data {new Date(event.post_event_date ?? event.pre_event_date).getUTCFullYear()}.
          </p>
        )}
      </section>

      <section>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>침수 오버레이 지도</h2>
        {hasFloodOverlay && floodOverlayBounds ? (
          <FloodOverlayMap
            overlayUrl={`/api/tiles/${id}/flood_overlay_preview.png`}
            bounds={floodOverlayBounds as [[number, number], [number, number], [number, number], [number, number]]}
          />
        ) : (
          <p style={{ color: "#666" }}>이 이벤트는 침수 오버레이가 아직 생성되지 않았습니다.</p>
        )}
      </section>

      <section>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>피해 통계 (시군 단위)</h2>
        {adm3Stats.length === 0 ? (
          <p style={{ color: "#666" }}>노출도 데이터가 없습니다.</p>
        ) : (
          <>
            <div style={{ display: "flex", gap: 24, marginBottom: 12, fontSize: 14 }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{totalAreaKm2.toFixed(2)} km²</div>
                <div style={{ color: "#666" }}>총 침수 면적</div>
              </div>
              <div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{totalPop.toLocaleString()}</div>
                <div style={{ color: "#666" }}>추정 영향 인구</div>
              </div>
              <div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{totalBuildings.toLocaleString()}</div>
                <div style={{ color: "#666" }}>추정 영향 건물</div>
              </div>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>
                  <th style={{ padding: "6px 8px" }}>시군</th>
                  <th style={{ padding: "6px 8px" }}>침수 면적</th>
                  <th style={{ padding: "6px 8px" }}>비율</th>
                  <th style={{ padding: "6px 8px" }}>인구</th>
                  <th style={{ padding: "6px 8px" }}>건물</th>
                </tr>
              </thead>
              <tbody>
                {adm3Stats
                  .slice()
                  .sort((a, b) => Number(b.flooded_area_km2) - Number(a.flooded_area_km2))
                  .map((s, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "6px 8px" }}>{(s.admin_boundaries as unknown as AdminBoundaryRef)?.name}</td>
                      <td style={{ padding: "6px 8px" }}>{Number(s.flooded_area_km2).toFixed(4)} km²</td>
                      <td style={{ padding: "6px 8px" }}>{Number(s.flooded_area_pct).toFixed(2)}%</td>
                      <td style={{ padding: "6px 8px" }}>{s.est_population_affected ?? "—"}</td>
                      <td style={{ padding: "6px 8px" }}>{s.est_buildings_affected ?? "—"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <p style={{ fontSize: 12, color: "#999" }}>
        AI 추정치이며 공식 재해 판정이 아닙니다. PAGASA/지자체 공식 발표를 함께 확인하세요.
      </p>
    </div>
  );
}
