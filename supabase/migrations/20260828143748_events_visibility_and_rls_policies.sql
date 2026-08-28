-- Week 1-3: draft RLS policies for spec.md §4's three roles (admin / viewer / public).
--
-- Scope note (docs/design-notes.md has the full reasoning): this is a *draft*,
-- not the final wiring. Two things are still genuinely Week 4's job:
--   1. Real Supabase Auth login for LGU/NGO viewers — until then, "viewer" is
--      approximated by Postgres's built-in `authenticated` role.
--   2. Distinguishing a human *admin* from a human *viewer* once both are
--      logged-in `authenticated` users — that needs a role claim (custom JWT
--      claim or a user_roles table), which doesn't exist yet. For now, "admin"
--      is simply the service_role key the pipeline backend holds — service_role
--      bypasses RLS entirely, so it already has full read/write with zero
--      policies needed.
--
-- What *is* real today: anon (spec's "public") vs authenticated (spec's
-- "viewer") vs service_role (spec's "admin") is a genuine, testable 3-tier
-- read boundary, enforced by Postgres itself, not just app-level convention.

-- ---------------------------------------------------------------------------
-- events.visibility — missing piece needed to implement "공개 이벤트에 한해
-- public 열람 가능" (spec.md §2 In / §4). Without this, there's no way to
-- distinguish a public-facing event from an LGU-internal one.
-- ---------------------------------------------------------------------------

alter table public.events
  add column visibility text not null default 'private'
    check (visibility in ('public', 'private'));

comment on column public.events.visibility is
  'public = visible to anon (spec.md §4 "public" role); private = requires authenticated (viewer) or service_role (admin). Defaults to private so nothing is public by accident.';

-- ---------------------------------------------------------------------------
-- Reference data with no sensitivity: readable by everyone, including anon.
-- ---------------------------------------------------------------------------

create policy aois_select_all
  on public.aois for select
  to anon, authenticated
  using (true);

create policy admin_boundaries_select_all
  on public.admin_boundaries for select
  to anon, authenticated
  using (true);

-- ---------------------------------------------------------------------------
-- events: anon sees only completed + public events. authenticated (viewer)
-- sees all completed events regardless of visibility (LGU/NGO gets the full
-- picture, not just what's been made public). Neither can see 'registered'/
-- 'processing'/'failed' events — those are pipeline-internal until done.
-- ---------------------------------------------------------------------------

create policy events_select_public
  on public.events for select
  to anon
  using (status = 'completed' and visibility = 'public');

create policy events_select_viewer
  on public.events for select
  to authenticated
  using (status = 'completed');

-- ---------------------------------------------------------------------------
-- flood_extents / exposure_stats / reports: same event-visibility rule,
-- applied via EXISTS against the events table above (avoids duplicating the
-- status/visibility logic three times with copy-paste drift risk).
-- ---------------------------------------------------------------------------

create policy flood_extents_select_public
  on public.flood_extents for select
  to anon
  using (exists (
    select 1 from public.events e
    where e.id = flood_extents.event_id and e.status = 'completed' and e.visibility = 'public'
  ));

create policy flood_extents_select_viewer
  on public.flood_extents for select
  to authenticated
  using (exists (
    select 1 from public.events e
    where e.id = flood_extents.event_id and e.status = 'completed'
  ));

create policy exposure_stats_select_public
  on public.exposure_stats for select
  to anon
  using (exists (
    select 1 from public.events e
    where e.id = exposure_stats.event_id and e.status = 'completed' and e.visibility = 'public'
  ));

create policy exposure_stats_select_viewer
  on public.exposure_stats for select
  to authenticated
  using (exists (
    select 1 from public.events e
    where e.id = exposure_stats.event_id and e.status = 'completed'
  ));

create policy reports_select_public
  on public.reports for select
  to anon
  using (exists (
    select 1 from public.events e
    where e.id = reports.event_id and e.status = 'completed' and e.visibility = 'public'
  ));

create policy reports_select_viewer
  on public.reports for select
  to authenticated
  using (exists (
    select 1 from public.events e
    where e.id = reports.event_id and e.status = 'completed'
  ));

-- ---------------------------------------------------------------------------
-- scene_refs / inference_runs / pipeline_events: deliberately NO anon or
-- authenticated policies. These are pipeline-internal (STAC ids, storage
-- bucket keys, raw model metrics, full audit trail) — spec.md §4 only
-- promises viewers "대시보드 열람, 리포트 다운로드", not pipeline internals.
-- With RLS enabled and zero policies for these roles, anon/authenticated get
-- zero rows; only service_role (admin/pipeline backend) can read them.
-- ---------------------------------------------------------------------------

-- (no policies here — the absence is the policy)

-- ---------------------------------------------------------------------------
-- No INSERT/UPDATE/DELETE policies for anon or authenticated anywhere: all
-- writes go through the pipeline backend's service_role key, which bypasses
-- RLS. This is intentional, not an oversight — spec.md §4 gives write access
-- to admin only.
-- ---------------------------------------------------------------------------
