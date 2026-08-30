-- Week 4-8: adds 'watchdog.stale_check' as a valid pipeline_events.step value.
-- The Cloudflare Worker Cron watchdog (workers/stale-event-watchdog/) needs
-- to log its own audit trail into the same insert-only pipeline_events table
-- the Python pipeline already writes to (spec.md §7/§13) — same table, same
-- insert-only guarantee (BEFORE UPDATE/DELETE trigger, untouched here), just
-- one more valid step name. Mirrors pipeline/db.py's VALID_STEPS set — keep
-- both in sync (that file's own module docstring already says this).
--
-- Postgres has no ALTER CONSTRAINT for CHECK — drop + recreate is the only
-- way to widen it. The name below is the default Postgres auto-assigns to an
-- inline `column type CHECK (...)` with no explicit CONSTRAINT name
-- (`<table>_<column>_check`), confirmed against the original migration
-- (20260828142445_initial_schema.sql) which defined it exactly that way.
alter table public.pipeline_events
  drop constraint if exists pipeline_events_step_check;

alter table public.pipeline_events
  add constraint pipeline_events_step_check check (step in (
    'aois.list_watched', 'events.create', 'scenes.fetch', 'preprocess.run',
    'inference.run', 'baseline.diff', 'vectorize.extract', 'exposure.compute',
    'tiles.publish', 'reports.generate', 'watchdog.stale_check'
  ));
