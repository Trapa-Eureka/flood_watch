-- Week 4-9: 인증/역할 적용 — closes the two gaps
-- 20260828143748_events_visibility_and_rls_policies.sql's own header already
-- named as Week 4's job: (1) real Supabase Auth login so a human viewer can
-- actually become `authenticated` instead of that tier being theoretical,
-- and (2) distinguishing admin from viewer among authenticated users, which
-- needs a role somewhere — this table is that "somewhere".
--
-- Scope note: this table/function only back the READ-side "is this logged-in
-- user an admin" checks (both a defense-in-depth RLS policy below, and the
-- Next.js middleware/route guards in web/middleware.ts + the API routes).
-- All actual admin WRITES (events.create, pipeline run trigger) still go
-- through the Next.js backend's service_role key exactly as before — they
-- don't need a parallel RLS write policy for `authenticated`+admin because
-- nothing calls Supabase directly from the browser with the admin's own JWT
-- for writes. Not built here on purpose: it would be unused surface area.

create table public.user_roles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  role text not null check (role in ('admin', 'viewer')),
  created_at timestamptz not null default now()
);

comment on table public.user_roles is
  'spec.md §4 role for one authenticated user. No self-service role assignment — rows are inserted directly (service_role) by whoever administers this project, not by a signup flow. A user with no row here is treated as viewer-tier at most by every check that reads this table (see is_admin()).';

alter table public.user_roles enable row level security;

-- A logged-in user can read their own role row (the Next.js app needs this
-- to decide what UI to show) — nothing else. No policy for anon (not
-- logged in, nothing to read) and no insert/update/delete policy for
-- authenticated (role assignment is a service_role-only action, matching
-- every other write boundary already established in this project).
create policy user_roles_select_own
  on public.user_roles for select
  to authenticated
  using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- is_admin() — SECURITY DEFINER so RLS policies on OTHER tables (below) can
-- check role without needing user_roles' own RLS opened up to every caller.
-- Same pattern this project already uses elsewhere for cross-table RLS
-- checks (see docs/design-notes.md's SECURITY DEFINER notes from Week 3).
-- ---------------------------------------------------------------------------

create or replace function public.is_admin()
returns boolean
language sql
security definer
stable
set search_path = public
as $$
  select exists (
    select 1 from public.user_roles
    where user_id = auth.uid() and role = 'admin'
  );
$$;

comment on function public.is_admin() is
  'true iff the current request''s auth.uid() has an admin row in user_roles. false (not an error) for anon (auth.uid() is null) or any authenticated user with no admin row.';

grant execute on function public.is_admin() to anon, authenticated;

-- ---------------------------------------------------------------------------
-- Defense-in-depth: give a logged-in admin RLS-level full read access too,
-- not just via the Next.js backend's service_role key. Read-only (see scope
-- note above for why no write policies) — lets a future direct-Supabase-
-- client admin view work without inventing a new access path, and means
-- the RLS layer itself agrees with "admin sees everything", not just the
-- application code's own judgment call.
-- ---------------------------------------------------------------------------

create policy events_select_admin
  on public.events for select
  to authenticated
  using (public.is_admin());

create policy flood_extents_select_admin
  on public.flood_extents for select
  to authenticated
  using (public.is_admin());

create policy exposure_stats_select_admin
  on public.exposure_stats for select
  to authenticated
  using (public.is_admin());

create policy reports_select_admin
  on public.reports for select
  to authenticated
  using (public.is_admin());

create policy scene_refs_select_admin
  on public.scene_refs for select
  to authenticated
  using (public.is_admin());

create policy inference_runs_select_admin
  on public.inference_runs for select
  to authenticated
  using (public.is_admin());

create policy pipeline_events_select_admin
  on public.pipeline_events for select
  to authenticated
  using (public.is_admin());
