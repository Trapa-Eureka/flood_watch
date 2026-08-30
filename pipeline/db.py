"""Spec §7 + §13: pipeline_events insert-only audit logging (Week 1-7).

Every pipeline stage's input/output is meant to land here — spec.md §13's
CLAUDE.md rule: "재현 불가능한 추론 실행 금지" (pipeline_events에 insert-only로
기록). The table itself already enforces insert-only at the DB level
(supabase/migrations/20260828142445_initial_schema.sql: a BEFORE UPDATE/DELETE
trigger rejects both, verified live in Week 1-3). This module deliberately
only ever POSTs new rows — there is no update/delete function here to reach
for by mistake, so the DB-level guarantee and the app-level API agree.

Writes go through Supabase's PostgREST REST API using the service_role key
(bypasses RLS — Week 1-3's RLS policies give anon/authenticated zero access to
this table on purpose, see docs/design-notes.md). No supabase-py/psycopg2
dependency: `requests` is already a dependency, and pipeline_events writes are
simple single-row inserts — a full DB client would be more machinery than
this needs.

Usage — plain insert:
    from pipeline.db import log_pipeline_event
    log_pipeline_event("aois.list_watched", "success", output={"count": 4})

Usage — context manager (logs success/failure automatically, including on
exceptions, so a stage can't accidentally skip logging its own failure):
    from pipeline.db import pipeline_step

    with pipeline_step("scenes.fetch", event_id=event_id, input={"bbox": bbox}) as step:
        result = fetch_best_s2_scenes(bbox, ...)
        step.output = {"post_event_item_id": result["post_event"]["item"].id}
    # success path logs status="success", output=step.output
    # exception path logs status="failed", output={"error": "..."}, then re-raises
"""
import os
from contextlib import contextmanager
from typing import Optional

import requests

from pipeline import config

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Mirrors the `step` CHECK constraint in supabase/migrations/
# 20260828142445_initial_schema.sql (widened by 20260830110000_pipeline_
# events_watchdog_step.sql) — keep both lists in sync. A step not in this set
# fails fast here with a clear Python error, instead of a 400 from PostgREST
# that's one layer further from the mistake.
#
# "watchdog.stale_check" is written by the Cloudflare Worker Cron watchdog
# (workers/stale-event-watchdog/, Week 4-8), not by this Python module — it's
# listed here purely so this set stays the single source of truth for "every
# step name that's actually valid," even though nothing in pipeline/ itself
# ever logs it.
VALID_STEPS = {
    "aois.list_watched", "events.create", "scenes.fetch", "preprocess.run",
    "inference.run", "baseline.diff", "vectorize.extract", "exposure.compute",
    "tiles.publish", "reports.generate", "watchdog.stale_check",
}


def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY not found in .env (set during Week 1-3 project setup) — "
            "pipeline_events logging needs it to bypass RLS (Week 1-3 policies give anon/"
            "authenticated zero access to this table on purpose). See .env.example."
        )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def log_pipeline_event(step: str, status: str, input=None, output=None,
                        event_id: Optional[str] = None, run_id: Optional[str] = None) -> dict:
    """Insert one pipeline_events row and return it. The only write operation
    this module offers, on purpose — matches the table's own insert-only
    DB-level trigger."""
    if step not in VALID_STEPS:
        raise ValueError(f"Unknown pipeline step {step!r} — must be one of {sorted(VALID_STEPS)}")
    if status not in ("success", "failed"):
        raise ValueError(f"status must be 'success' or 'failed', got {status!r}")

    url = f"{config.SUPABASE_URL}/rest/v1/pipeline_events"
    row = {
        "step": step, "status": status, "input": input, "output": output,
        "event_id": event_id, "run_id": run_id,
    }
    resp = requests.post(url, headers=_supabase_headers(), json=row, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"pipeline_events insert failed ({resp.status_code}): {resp.text}")
    return resp.json()[0]


def touch_event(event_id: Optional[str]) -> None:
    """Week 4-8 finding, discovered live: events.updated_at previously only
    changed at pipeline start/end (repository.update_event_status()'s two
    calls per run), never on the individual steps in between. That's exactly
    the column BOTH staleness checks read — web/app/api/events/[id]/run/
    route.ts's manual-retry guard and the Cloudflare Worker Cron watchdog
    (workers/stale-event-watchdog/) — to tell "genuinely still working" from
    "actually dead." Called automatically by pipeline_step() on every
    successfully-logged step (see below), AND called directly (public on
    purpose, not `_`-prefixed) from inside orchestrator.py's exposure.compute
    loop — that step alone was measured taking 45+ minutes in a real run
    (ADM4 barangay-level exposure over a slow external building-footprint
    API, see docs/design-notes.md "Week 4-8"), entirely inside ONE
    pipeline_step() context, so the once-per-step call alone still leaves a
    45-minute gap. A single per-step touch was not enough; anywhere a single
    step can itself run long enough to approach the staleness threshold
    needs its own periodic touch call.

    Best-effort: a failure here must never break the actual pipeline step it
    was called from, so it's swallowed (with a stderr note) rather than
    raised."""
    if not event_id:
        return
    try:
        url = f"{config.SUPABASE_URL}/rest/v1/events"
        # Re-PATCHing id to its own value is a genuine column write (fires
        # the set_updated_at trigger) without changing anything else about
        # the row — same technique repository.update_event_status() uses
        # for its own (real) status changes, just with a no-op value here.
        requests.patch(url, headers=_supabase_headers(), params={"id": f"eq.{event_id}"}, json={"id": event_id}, timeout=10)
    except Exception as e:  # noqa: BLE001 — liveness heartbeat only, never fatal
        print(f"  (warning) touch_event({event_id}) failed, non-fatal: {type(e).__name__}: {e}")


class _StepContext:
    def __init__(self, input):
        self.input = input
        self.output = None


@contextmanager
def pipeline_step(step: str, event_id: Optional[str] = None, run_id: Optional[str] = None, input=None):
    """See module docstring. Yields a mutable context object — set `.output`
    inside the `with` block; that's what gets logged when it exits."""
    ctx = _StepContext(input)
    try:
        yield ctx
    except Exception as e:  # noqa: BLE001 — deliberately broad: log *any* failure, then re-raise it unchanged
        log_pipeline_event(
            step, "failed", input=input, output={"error": f"{type(e).__name__}: {e}"},
            event_id=event_id, run_id=run_id,
        )
        touch_event(event_id)
        raise
    else:
        log_pipeline_event(step, "success", input=input, output=ctx.output, event_id=event_id, run_id=run_id)
        touch_event(event_id)
