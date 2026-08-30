/**
 * Week 4-8: Cloudflare Worker Cron — the "Workers Cron 연동" half of this
 * week's sprint item. spec.md §5 always described the intended
 * orchestration layer as "Cloudflare Workers Cron(관리자 트리거 후 상태
 * 폴링)" — admin triggers (already built, Week4-6's /admin UI + POST
 * /api/events/{id}/run), Workers Cron does the status polling. The heavy
 * Python/GDAL/rasterio pipeline itself CANNOT run inside a Workers isolate
 * (no Python runtime, no native deps) — that was never this Worker's job.
 * What Workers Cron can do, and what was still genuinely missing, is
 * SERVER-SIDE status polling that runs independent of any admin's open
 * browser tab.
 *
 * Concretely, this closes a real gap Week4-6 documented and explicitly
 * deferred here: EventPipelineList.tsx's client-side setInterval polling
 * only runs while an admin's browser tab is open — if a background pipeline
 * subprocess dies (this project already hit this for real once: a Claude
 * Code session restart killed a detached child mid-GPU-inference), the
 * event is stuck at status='processing' forever, with nothing watching
 * unless someone happens to reopen /admin and click retry. Week4-6's own
 * mitigation was reactive-only: POST /api/events/{id}/run treats a
 * 'processing' event as stale (and allows retry) if updated_at is >20min
 * old, but ONLY checks that when someone manually clicks the button again.
 * This Worker makes that check proactive: every 5 minutes, regardless of
 * whether anyone is looking at the dashboard, sweep for stale 'processing'
 * events and mark them 'failed' — so the admin sees an accurate FAILED
 * status (and can retry) instead of a silently-stuck PROCESSING that lies
 * about the real state of the system.
 *
 * Real deploy: `wrangler deploy` (this directory). Secret:
 * `wrangler secret put SUPABASE_SERVICE_ROLE_KEY` (see wrangler.toml's
 * comment on why anon isn't enough here).
 */

export interface Env {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  STALE_MINUTES: string;
}

interface StaleEventRow {
  id: string;
  name: string;
  updated_at: string;
}

async function sweepStaleEvents(env: Env): Promise<void> {
  // NOT `Number(env.STALE_MINUTES) || 20` — found live during this week's
  // own local dev test: 0 is a legitimate override value (used to verify
  // this logic against a real just-created event without waiting 20 real
  // minutes) but `0 || 20` silently discards it because 0 is falsy in JS,
  // which is exactly what happened and masked a real bug until checked
  // against the actual DB state instead of just the 200 OK response.
  const parsedStaleMinutes = Number(env.STALE_MINUTES);
  const staleMinutes = Number.isFinite(parsedStaleMinutes) ? parsedStaleMinutes : 20;
  const thresholdIso = new Date(Date.now() - staleMinutes * 60 * 1000).toISOString();

  const headers = {
    apikey: env.SUPABASE_SERVICE_ROLE_KEY,
    Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,
    "Content-Type": "application/json",
  };

  // Same two conditions web/app/api/events/[id]/run/route.ts's manual
  // staleness check uses (status='processing' AND updated_at older than the
  // threshold) — just evaluated proactively here instead of on next click.
  const queryUrl =
    `${env.SUPABASE_URL}/rest/v1/events?status=eq.processing` +
    `&updated_at=lt.${encodeURIComponent(thresholdIso)}&select=id,name,updated_at`;

  const res = await fetch(queryUrl, { headers });
  if (!res.ok) {
    console.error(`stale-event-watchdog: query failed (${res.status}): ${await res.text()}`);
    return;
  }

  const staleEvents = (await res.json()) as StaleEventRow[];
  if (staleEvents.length === 0) {
    console.log("stale-event-watchdog: no stale processing events");
    return;
  }

  for (const ev of staleEvents) {
    const ageMin = Math.round((Date.now() - new Date(ev.updated_at).getTime()) / 60000);
    console.warn(`stale-event-watchdog: event ${ev.id} (${ev.name}) stuck at processing for ${ageMin}min — marking failed`);

    const patchRes = await fetch(`${env.SUPABASE_URL}/rest/v1/events?id=eq.${ev.id}`, {
      method: "PATCH",
      headers: { ...headers, Prefer: "return=minimal" },
      body: JSON.stringify({ status: "failed" }),
    });
    if (!patchRes.ok) {
      console.error(`stale-event-watchdog: failed to mark event ${ev.id} failed (${patchRes.status}): ${await patchRes.text()}`);
      continue;
    }

    // Audit trail in the same insert-only pipeline_events table the Python
    // side writes to (spec.md §7/§13) — 'watchdog.stale_check' is a valid
    // step as of supabase/migrations/20260830110000_pipeline_events_
    // watchdog_step.sql, mirrored in pipeline/db.py's VALID_STEPS.
    const logRes = await fetch(`${env.SUPABASE_URL}/rest/v1/pipeline_events`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        event_id: ev.id,
        step: "watchdog.stale_check",
        status: "failed",
        output: {
          reason: `stuck at status=processing for ${ageMin}min (no updated_at change) — marked failed by Cloudflare Worker Cron watchdog`,
          stale_minutes_threshold: staleMinutes,
        },
      }),
    });
    if (!logRes.ok) {
      console.error(`stale-event-watchdog: failed to log pipeline_events for ${ev.id} (${logRes.status}): ${await logRes.text()}`);
    }
  }
}

export default {
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(sweepStaleEvents(env));
  },
};
