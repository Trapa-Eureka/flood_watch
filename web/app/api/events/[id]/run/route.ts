import { NextResponse } from "next/server";
import { spawn } from "child_process";
import { existsSync, mkdirSync, openSync } from "fs";
import path from "path";
import supabaseAdmin from "@/lib/supabase-admin";
import { requireAdmin } from "@/lib/require-admin";

// POST /api/events/{id}/run — Week4-6 admin trigger UI: kicks off
// pipeline/orchestrator.py's run_event_pipeline(event_id) as a detached
// background process and returns immediately (202) rather than blocking the
// HTTP request for the 3-6 minutes a real run takes (Week2-4's own measured
// GPU inference alone is 76-160s) — the frontend polls GET .../status
// instead of waiting on this response.
//
// This is a local-subprocess stand-in for a real job queue — same honest
// "works because this one machine runs both the Next server and the Python
// pipeline, won't survive an actual deploy" caveat already applied to
// Week4-3's /api/tiles local file-serving bridge. Week4-8 ("Modal 배포
// 정식화 + Workers Cron 연동") is where a real queue replaces this; not
// solved here, not silently ignored either.
const REPO_ROOT = path.resolve(process.cwd(), "..");
const PYTHON_BIN = path.join(REPO_ROOT, ".venv", "bin", "python3");
const EVENTS_OUTPUT_DIR = path.join(REPO_ROOT, "data", "output", "events");

export async function POST(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = await requireAdmin();
  if (denied) return denied;

  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    return NextResponse.json({ error: "invalid event id" }, { status: 400 });
  }

  const supabase = supabaseAdmin();
  const { data: event, error } = await supabase.from("events").select("id, status, updated_at").eq("id", id).single();
  if (error || !event) return NextResponse.json({ error: "event not found" }, { status: 404 });
  if (event.status === "processing") {
    // No PID/liveness tracking exists yet for the background subprocess
    // (that's real job-queue territory — Week4-8's job, not this route's) —
    // found live during this week's own end-to-end test: a run that gets
    // killed externally (this exact test hit a session interruption mid-run)
    // leaves events.status stuck at 'processing' forever with no way to
    // retry, since nothing ever calls update_event_status again. STALE_MS
    // is a pragmatic mitigation, not real health-checking: a real run
    // finishes in 3-6 minutes (Week2-4's own measured GPU inference alone
    // is 76-160s), so anything still "processing" well past that is almost
    // certainly dead, not still legitimately working.
    const STALE_MS = 20 * 60 * 1000;
    const ageMs = Date.now() - new Date(event.updated_at).getTime();
    if (ageMs < STALE_MS) {
      return NextResponse.json({ error: "pipeline is already running for this event" }, { status: 409 });
    }
    console.warn(`event ${id} was stuck at status=processing for ${Math.round(ageMs / 60000)}min — treating as stale, allowing retrigger`);
  }

  if (!existsSync(PYTHON_BIN)) {
    return NextResponse.json(
      { error: `python venv not found at ${PYTHON_BIN} — run "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" from the repo root` },
      { status: 500 },
    );
  }

  const eventLogDir = path.join(EVENTS_OUTPUT_DIR, id);
  mkdirSync(eventLogDir, { recursive: true });
  const logPath = path.join(eventLogDir, "run.log");
  const logFd = openSync(logPath, "a");

  // detached + unref: the child outlives this request/response cycle. stdout
  // and stderr both go to the same log file (unbuffered order matters less
  // here than just having everything in one place to read after the fact —
  // same "-u + real log file" fix Week4-3's design-notes.md already
  // documented needing for a background pipeline run).
  const child = spawn(PYTHON_BIN, ["-u", "-m", "pipeline.orchestrator", id], {
    cwd: REPO_ROOT,
    detached: true,
    stdio: ["ignore", logFd, logFd],
  });
  child.unref();

  return NextResponse.json(
    { ok: true, pid: child.pid, logPath: `data/output/events/${id}/run.log` },
    { status: 202 },
  );
}
