import { NextResponse } from "next/server";
import { spawnSync } from "child_process";
import { existsSync, readFileSync } from "fs";
import path from "path";
import supabaseServer from "@/lib/supabase-server";

// GET /api/events/{id}/report — Week4-7: serves pipeline/reports.py's
// generate_event_report() output (data/output/reports/{id}/report.pdf).
//
// Session-aware client (Week 4-9), NOT supabaseAdmin() — same reasoning as
// events/[id]/page.tsx: this is a download link real visitors hit, so it
// must go through the same RLS boundary a real visitor hits — for whoever
// they actually are (anon/viewer/admin), not always anon regardless of
// login. A processing/failed event, or a private one this caller isn't
// entitled to, is invisible under RLS, so the .single() lookup below
// already gates correctly without a separate status/visibility check.
//
// Generate-if-missing, synchronous: unlike Week4-6's GPU pipeline run
// (3-6 minutes, backgrounded via detached spawn + polling), Chrome-headless
// --print-to-pdf is a few seconds with no GPU involved — spawnSync and just
// block the request is the honest choice here, not a shortcut. If the PDF
// already exists on disk (the common case: a report was generated once,
// either by an earlier download or manually), it's served straight off
// disk with no regeneration — same local-bridge convention as
// /api/tiles/[eventId]/[filename], and it also avoids inserting a fresh
// `reports` row (create_report() always inserts, never upserts — see
// pipeline/repository.py) on every single download click.
const REPO_ROOT = path.resolve(process.cwd(), "..");
const PYTHON_BIN = path.join(REPO_ROOT, ".venv", "bin", "python3");
const REPORTS_ROOT = path.join(REPO_ROOT, "data", "output", "reports");

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    return NextResponse.json({ error: "invalid event id" }, { status: 400 });
  }

  const supabase = await supabaseServer();
  const { data: event, error } = await supabase.from("events").select("id, name").eq("id", id).single();
  if (error || !event) return NextResponse.json({ error: "event not found" }, { status: 404 });

  const pdfPath = path.join(REPORTS_ROOT, id, "report.pdf");

  if (!existsSync(pdfPath)) {
    if (!existsSync(PYTHON_BIN)) {
      return NextResponse.json(
        { error: `python venv not found at ${PYTHON_BIN} — run "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" from the repo root` },
        { status: 500 },
      );
    }

    // pipeline/reports.py's own Chrome-headless subprocess has a 60s
    // timeout internally; give the outer call some headroom above that
    // rather than racing it.
    const result = spawnSync(PYTHON_BIN, ["-u", "-m", "pipeline.reports", id], {
      cwd: REPO_ROOT,
      timeout: 90_000,
      encoding: "utf-8",
    });

    if (result.error || result.status !== 0 || !existsSync(pdfPath)) {
      console.error(`report generation failed for event ${id}:`, result.stderr || result.error);
      return NextResponse.json({ error: "report generation failed", detail: result.stderr?.slice(-2000) }, { status: 500 });
    }
  }

  const data = readFileSync(pdfPath);
  return new NextResponse(new Uint8Array(data), {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="flood-report-${id}.pdf"`,
      "Cache-Control": "public, max-age=3600",
    },
  });
}
