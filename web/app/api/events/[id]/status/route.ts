import { NextResponse } from "next/server";
import supabaseAdmin from "@/lib/supabase-admin";
import { requireAdmin } from "@/lib/require-admin";

// GET /api/events/{id}/status — Week4-6 admin trigger UI polling target.
// Returns the event's current status plus every pipeline_events row logged
// for it so far (real audit-log rows written by pipeline/orchestrator.py's
// pipeline_step() calls, not a synthesized progress bar) — service_role,
// same reasoning as the rest of /api/events: 'processing'/'failed' events
// aren't visible to anon/authenticated at all (Week1-3 RLS), and
// pipeline_events (raw step-level errors, internal timings) isn't part of
// spec.md §4's viewer promise ("대시보드 열람, 리포트 다운로드") at all —
// admin-only, enforced by requireAdmin() below since Week 4-9.
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = await requireAdmin();
  if (denied) return denied;

  const { id } = await params;
  const supabase = supabaseAdmin();

  const { data: event, error } = await supabase.from("events").select("id, name, status").eq("id", id).single();
  if (error || !event) return NextResponse.json({ error: "event not found" }, { status: 404 });

  const { data: steps } = await supabase
    .from("pipeline_events")
    .select("step, status, created_at, output")
    .eq("event_id", id)
    .order("created_at", { ascending: true });

  return NextResponse.json({ event, steps: steps ?? [] });
}
