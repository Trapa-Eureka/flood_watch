"""Spec §7 reports.generate: per-event PDF report. spec.md §9 explicitly says
"기존 PDF 생성기 재사용" (reuse an existing generator, don't build a new
PDF-rendering stack) — this reuses the HTML -> Chrome-headless
--print-to-pdf pipeline already proven working in this user's other projects
(SONG ERP's manuals, Li-sys reports, per this user's own memory notes),
rather than adding a new Python PDF dependency. weasyprint specifically is
broken on this Mac (missing native libgobject) and reportlab/fpdf would mean
hand-laying-out tables/images in a drawing API instead of plain HTML/CSS —
Chrome headless needs zero new pip installs, this Mac already has it.

Usage:
  python -m pipeline.reports <event_id>
"""
import os
import subprocess
from pathlib import Path
from typing import Optional

import requests

from pipeline import config, repository
from pipeline.db import pipeline_step

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Same path the memory note's fastest-verified pipeline uses on this Mac.
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

KIND_LABELS = {"typhoon": "Typhoon", "monsoon": "Monsoon", "manual": "Manual", "backtest": "Backtest"}


def _headers() -> dict:
    """Same pattern as pipeline/db.py's _supabase_headers() and
    pipeline/repository.py's _headers() — each module that talks to
    PostgREST directly keeps its own copy rather than reaching into another
    module's underscore-prefixed internals (this project's established
    convention, not an oversight)."""
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not found in .env — see .env.example.")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _check(resp: requests.Response, what: str):
    if resp.status_code >= 400:
        raise RuntimeError(f"{what} failed ({resp.status_code}): {resp.text}")


def _fetch_report_data(event_id: str) -> dict:
    """One composed read across events/aois/exposure_stats/admin_boundaries —
    a report-shaped join, not a single-table CRUD op, so it lives here
    rather than in repository.py's per-table helpers."""
    headers = _headers()

    ev_resp = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/events",
        headers=headers,
        params={"id": f"eq.{event_id}", "select": "id,name,kind,pre_event_date,post_event_date,aois(name)"},
        timeout=30,
    )
    _check(ev_resp, "events fetch")
    rows = ev_resp.json()
    if not rows:
        raise RuntimeError(f"event {event_id} not found")
    event = rows[0]

    stats_resp = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/exposure_stats",
        headers=headers,
        params={
            "event_id": f"eq.{event_id}",
            "select": "flooded_area_km2,flooded_area_pct,est_population_affected,est_buildings_affected,admin_boundaries(name,level)",
        },
        timeout=30,
    )
    _check(stats_resp, "exposure_stats fetch")
    stats = stats_resp.json()
    # Week3-9 lesson (see events/[id]/page.tsx for the original fix, applied
    # identically here): exposure_stats holds BOTH adm3_municipality and
    # adm4_barangay rows — summing across both double-counts the same area.
    adm3_stats = [s for s in stats if (s.get("admin_boundaries") or {}).get("level") == "adm3_municipality"]

    return {"event": event, "adm3_stats": adm3_stats}


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_html(event_id: str, data: dict, tiles_dir: Path) -> str:
    event = data["event"]
    stats = data["adm3_stats"]
    aoi_name = (event.get("aois") or {}).get("name") or "No AOI"
    kind_label = KIND_LABELS.get(event["kind"], event["kind"])

    pre_path = tiles_dir / "pre_rgb_preview.jpg"
    post_path = tiles_dir / "post_rgb_preview.jpg"
    flood_path = tiles_dir / "flood_overlay_preview.png"
    has_pre, has_post, has_flood = pre_path.exists(), post_path.exists(), flood_path.exists()

    post_date = event.get("post_event_date") or event["pre_event_date"]
    year = post_date[:4]

    total_area = sum(float(s["flooded_area_km2"]) for s in stats)
    total_pop = sum((s.get("est_population_affected") or 0) for s in stats)
    total_buildings = sum((s.get("est_buildings_affected") or 0) for s in stats)

    rows_html = "".join(
        f"""<tr>
          <td>{_esc((s.get('admin_boundaries') or {}).get('name', '?'))}</td>
          <td>{float(s['flooded_area_km2']):.4f} km&sup2;</td>
          <td>{float(s['flooded_area_pct']):.2f}%</td>
          <td>{s['est_population_affected'] if s.get('est_population_affected') is not None else '&mdash;'}</td>
          <td>{s['est_buildings_affected'] if s.get('est_buildings_affected') is not None else '&mdash;'}</td>
        </tr>"""
        for s in sorted(stats, key=lambda s: -float(s["flooded_area_km2"]))
    )

    images_html = ""
    if has_post:
        images_html += f"""
        <div class="img-block">
          <div class="img-label">Post-event ({post_date})</div>
          <div class="img-frame"><img src="file://{post_path}" /></div>
        </div>"""
    if has_pre:
        images_html += f"""
        <div class="img-block">
          <div class="img-label">Pre-event ({event['pre_event_date']})</div>
          <div class="img-frame"><img src="file://{pre_path}" /></div>
        </div>"""
    else:
        # Same honest fallback wording as BeforeAfterSlider.tsx — a real,
        # spec-anticipated case (no clean baseline scene), not an error.
        # Same .img-frame wrapper as the real-image case (fixed height, see
        # CSS) so this column lines up with the other two instead of
        # stretching/squeezing them — found via visual PDF inspection that
        # an earlier flex-centered version squeezed the "Pre-event" label
        # and the note text onto the same row instead of stacking them.
        images_html += """
        <div class="img-block">
          <div class="img-label">Pre-event</div>
          <div class="img-frame img-missing"><div class="img-missing-note">No pre-event image is available for this event &mdash; no baseline scene passed the AOI-local cloud-cover threshold right after the event (a real data limitation, not a display error).</div></div>
        </div>"""
    if has_flood:
        images_html += f"""
        <div class="img-block">
          <div class="img-label">Flood classification</div>
          <div class="img-frame"><img src="file://{flood_path}" /></div>
        </div>"""

    stats_block = (
        '<p style="color:#666;font-size:12px;">No exposure data available.</p>'
        if not stats
        else f"""
    <div class="stats-summary">
      <div><div class="stat-value">{total_area:.2f} km&sup2;</div><div class="stat-label">Total flooded area</div></div>
      <div><div class="stat-value">{total_pop:,.0f}</div><div class="stat-label">Est. population affected</div></div>
      <div><div class="stat-value">{total_buildings:,.0f}</div><div class="stat-label">Est. buildings affected</div></div>
    </div>
    <table>
      <thead><tr><th>Municipality</th><th>Flooded area</th><th>Pct</th><th>Population</th><th>Buildings</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>"""
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; color: #111; margin: 32px; }}
  h1 {{ font-size: 20px; margin-bottom: 2px; }}
  .subtitle {{ color: #666; font-size: 12px; margin-bottom: 20px; }}
  h2 {{ font-size: 14px; margin: 20px 0 8px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }}
  .images {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .img-block {{ flex: 1; min-width: 200px; }}
  .img-label {{ font-size: 11px; color: #666; margin-bottom: 4px; }}
  /* Fixed-height frame on every column (real image or the "missing" note) —
     found by visual inspection that a narrow/tall composite (e.g. Kristine's
     AOI) otherwise stretched the whole row's height via flex's default
     align-items:stretch, pushing the impact-stats table onto a mostly-blank
     second page. */
  .img-frame {{ height: 220px; border-radius: 4px; overflow: hidden; background: #f3f4f6; display: flex; align-items: center; justify-content: center; }}
  .img-frame img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .img-missing-note {{ font-size: 11px; color: #999; padding: 14px; text-align: center; }}
  .stats-summary {{ display: flex; gap: 24px; margin-bottom: 12px; }}
  .stat-value {{ font-size: 18px; font-weight: 700; }}
  .stat-label {{ font-size: 11px; color: #666; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{ text-align: left; border-bottom: 1px solid #e5e7eb; padding: 5px 6px; }}
  td {{ padding: 5px 6px; border-bottom: 1px solid #f3f4f6; }}
  .copernicus {{ font-size: 10px; color: #999; margin-top: 4px; }}
  .disclaimer {{ font-size: 11px; color: #999; margin-top: 24px; padding-top: 12px; border-top: 1px solid #e5e7eb; }}
  .generated {{ font-size: 10px; color: #bbb; margin-top: 4px; }}
</style></head>
<body>
  <h1>{_esc(event['name'])}</h1>
  <div class="subtitle">{kind_label} &middot; {_esc(aoi_name)} &middot; {event['pre_event_date']} &rarr; {event.get('post_event_date') or 'Ongoing'}</div>

  <h2>Before / After</h2>
  <div class="images">{images_html}</div>
  {f'<div class="copernicus">Contains modified Copernicus Sentinel data {year}.</div>' if has_post else ''}

  <h2>Impact Stats (municipality level)</h2>
  {stats_block}

  <div class="disclaimer">
    This is an AI-generated estimate, not an official disaster determination. Please check official PAGASA/LGU announcements as well.
    <div class="generated">Report generated by PH Flood Watch &middot; event id {event_id}</div>
  </div>
</body></html>"""


def generate_event_report(event_id: str, out_dir: Optional[Path] = None) -> Path:
    """spec.md §7 reports.generate. Returns the local PDF path — what the
    caller (Next.js's /api/events/{id}/report route, or a CLI run) does with
    it from there isn't this function's concern."""
    out_dir = Path(out_dir) if out_dir else config.DATA_OUTPUT_DIR / "reports" / event_id
    out_dir.mkdir(parents=True, exist_ok=True)
    tiles_dir = config.DATA_OUTPUT_DIR / "tiles" / event_id

    with pipeline_step("reports.generate", event_id=event_id) as ctx:
        data = _fetch_report_data(event_id)
        html = _render_html(event_id, data, tiles_dir)
        html_path = out_dir / "report.html"
        html_path.write_text(html, encoding="utf-8")

        pdf_path = out_dir / "report.pdf"
        if not Path(CHROME_PATH).exists():
            raise RuntimeError(
                f"Chrome not found at {CHROME_PATH} — this is the reused HTML->PDF pipeline "
                "(see docs/design-notes.md Week4-7), not a new dependency, but it does need "
                "Chrome installed at this exact path on this Mac."
            )
        cmd = [
            CHROME_PATH, "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}", f"file://{html_path}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0 or not pdf_path.exists():
            raise RuntimeError(f"Chrome headless print-to-pdf failed (exit {result.returncode}): {result.stderr[-2000:]}")

        repository.create_report(event_id, f"{event_id}/report.pdf")
        ctx.output = {"pdf_path": str(pdf_path), "size_bytes": pdf_path.stat().st_size}

    print(f"  reports: PDF saved to {pdf_path} ({pdf_path.stat().st_size / 1e3:.1f}KB)")
    return pdf_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    args = parser.parse_args()

    generate_event_report(args.event_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
