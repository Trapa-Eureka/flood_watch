-- PH Flood Watch — initial schema (spec.md §6 data model, formalized)
--
-- Turns the §6 "sketch" into a real, constrained PostGIS schema. Deliberate
-- refinements beyond the literal sketch (documented in docs/design-notes.md
-- under "Week 1-2"):
--   - uuid primary keys (gen_random_uuid()) instead of unspecified `id`.
--   - explicit NOT NULL / CHECK constraints for the enumerated `text` columns
--     the sketch only described in comments (e.g. events.kind).
--   - pipeline_events gets an `event_id` column in addition to `run_id`,
--     since several pipeline steps (aois.list_watched, events.create,
--     scenes.fetch) run before any inference_runs row exists — run_id alone
--     can't log them. run_id stays nullable, set only from inference.run
--     onward.
--   - pipeline_events is enforced append-only at the DB level (trigger),
--     matching spec.md §13's CLAUDE.md rule: "재현 불가능한 추론 실행 금지".
--   - admin_boundaries.source/vintage are NOT NULL, matching §13's rule:
--     "출처 불명 경계 데이터 사용 금지".
--   - RLS is enabled on every table now; actual admin/viewer/public policies
--     are written in Week 1-3 (sprint-plan.md). Until then, only the
--     service_role key (used by the pipeline backend) can read/write —
--     service_role bypasses RLS by design, so this doesn't block Week 1/2 work.
--
-- Extensions go into the `extensions` schema per Supabase convention; this
-- project's supabase/config.toml already puts `extensions` on the API
-- search_path, so no further config is needed for PostGIS types/functions
-- to resolve.

create extension if not exists postgis with schema extensions;
create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------------
-- Shared trigger functions
-- ---------------------------------------------------------------------------

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

comment on function public.set_updated_at() is
  'Generic BEFORE UPDATE trigger: stamps updated_at = now() on every row update.';

create or replace function public.pipeline_events_prevent_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'pipeline_events is insert-only (spec.md §13: 재현 불가능한 추론 실행 금지) — % not allowed', tg_op;
end;
$$;

comment on function public.pipeline_events_prevent_mutation() is
  'Blocks UPDATE/DELETE on pipeline_events so the pipeline audit trail can never be rewritten.';

-- ---------------------------------------------------------------------------
-- aois — monitored areas of interest (spec.md §6/§7)
-- ---------------------------------------------------------------------------

create table public.aois (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  -- 'river_basin' = the 4 priority-watch basins (Marikina/Cagayan/Bicol-Naga/Pampanga);
  -- 'custom' = a free-form AOI drawn/entered at event-registration time
  -- (2026-08-28 design decision — docs/design-notes.md).
  kind text not null check (kind in ('river_basin', 'custom')),
  geom extensions.geometry(Polygon, 4326) not null,
  -- 0 = not a priority-watch AOI (ad-hoc/event-only). Higher = checked more
  -- often by the (future) scheduled watch job. Nullable priority ordering is
  -- deliberately avoided — 0 is a valid, meaningful default.
  watch_priority int not null default 0,
  created_at timestamptz not null default now()
);

comment on table public.aois is
  'Monitored areas of interest — spec.md §6. watch_priority>0 = one of the priority-watch basins; the rest are free-form, created at event-registration time.';

create index aois_geom_gix on public.aois using gist (geom);
create index aois_watch_priority_idx on public.aois (watch_priority) where watch_priority > 0;

alter table public.aois enable row level security;

-- ---------------------------------------------------------------------------
-- events — a registered monitoring/backtest event (spec.md §6/§7)
-- ---------------------------------------------------------------------------

create table public.events (
  id uuid primary key default gen_random_uuid(),
  aoi_id uuid not null references public.aois (id) on delete restrict,
  name text not null,
  kind text not null check (kind in ('typhoon', 'monsoon', 'manual', 'backtest')),
  pre_event_date date not null,
  -- nullable: an ongoing/ongoing-monitoring event may not have a fixed end date yet.
  post_event_date date,
  status text not null default 'registered'
    check (status in ('registered', 'processing', 'completed', 'failed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint events_date_order check (post_event_date is null or post_event_date >= pre_event_date)
);

comment on table public.events is
  'A registered typhoon/monsoon/manual/backtest event to run the pipeline for — spec.md §6.';

create index events_aoi_id_idx on public.events (aoi_id);
create index events_status_idx on public.events (status);

create trigger events_set_updated_at
  before update on public.events
  for each row execute function public.set_updated_at();

alter table public.events enable row level security;

-- ---------------------------------------------------------------------------
-- scene_refs — satellite scenes collected for an event (spec.md §6/§7)
-- ---------------------------------------------------------------------------

create table public.scene_refs (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete restrict,
  stac_id text not null,
  collection text not null check (collection in ('sentinel-1-grd', 'sentinel-2-l2a')),
  role text not null check (role in ('baseline', 'post_event')),
  acquired_at timestamptz not null,
  footprint extensions.geometry(Polygon, 4326) not null,
  -- nullable until the asset is actually downloaded (scenes.fetch searches
  -- before it downloads — see pipeline/stac_client.py).
  storage_key text,
  created_at timestamptz not null default now(),
  unique (event_id, stac_id)
);

comment on table public.scene_refs is
  'STAC scenes (S1 GRD or S2 L2A) resolved for an event — spec.md §6/§7 scenes.fetch.';

create index scene_refs_event_id_idx on public.scene_refs (event_id);
create index scene_refs_footprint_gix on public.scene_refs using gist (footprint);

alter table public.scene_refs enable row level security;

-- ---------------------------------------------------------------------------
-- inference_runs — one Prithvi inference execution for an event (spec.md §6/§7)
-- ---------------------------------------------------------------------------

create table public.inference_runs (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete restrict,
  model text not null,
  model_version text,
  input_scene_ids jsonb not null default '[]'::jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'pending'
    check (status in ('pending', 'running', 'succeeded', 'failed')),
  metrics jsonb not null default '{}'::jsonb,
  constraint inference_runs_finished_after_started
    check (finished_at is null or finished_at >= started_at)
);

comment on table public.inference_runs is
  'One Prithvi+sen1floods11 inference execution — spec.md §6/§7 inference.run.';

create index inference_runs_event_id_idx on public.inference_runs (event_id);
create index inference_runs_status_idx on public.inference_runs (status);

alter table public.inference_runs enable row level security;

-- ---------------------------------------------------------------------------
-- flood_extents — the (post JRC-diff) new-flood polygon output (spec.md §6/§7)
-- ---------------------------------------------------------------------------

create table public.flood_extents (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete restrict,
  run_id uuid not null references public.inference_runs (id) on delete restrict,
  geom extensions.geometry(MultiPolygon, 4326) not null,
  area_km2 numeric not null check (area_km2 >= 0),
  -- Mean model confidence over the flooded area, 0-1. NOTE: this assumes a
  -- 0-1 probability scale from the model output — revisit if Week 2's actual
  -- inference_runs.metrics ends up using a different scale (e.g. 0-100).
  confidence_mean numeric check (confidence_mean is null or confidence_mean between 0 and 1),
  raster_storage_key text not null,
  created_at timestamptz not null default now()
);

comment on table public.flood_extents is
  'Vectorized new-flood extent after JRC permanent-water diff — spec.md §6/§7 baseline.diff + vectorize.extract.';

create index flood_extents_event_id_idx on public.flood_extents (event_id);
create index flood_extents_run_id_idx on public.flood_extents (run_id);
create index flood_extents_geom_gix on public.flood_extents using gist (geom);

alter table public.flood_extents enable row level security;

-- ---------------------------------------------------------------------------
-- admin_boundaries — ADM3/ADM4 reference boundaries (spec.md §6/§8)
-- ---------------------------------------------------------------------------

create table public.admin_boundaries (
  id uuid primary key default gen_random_uuid(),
  level text not null check (level in ('adm3_municipality', 'adm4_barangay')),
  name text not null,
  psgc_code text,
  geom extensions.geometry(MultiPolygon, 4326) not null,
  -- source/vintage are mandatory — spec.md §13: "출처 불명 경계 데이터 사용 금지".
  source text not null,
  vintage date not null,
  created_at timestamptz not null default now(),
  unique (level, psgc_code)
);

comment on table public.admin_boundaries is
  'ADM3 (municipality/city, stable) and ADM4 (barangay, community-sourced) boundaries — spec.md §6/§8. source+vintage always required.';

create index admin_boundaries_geom_gix on public.admin_boundaries using gist (geom);
create index admin_boundaries_name_idx on public.admin_boundaries (name);

alter table public.admin_boundaries enable row level security;

-- ---------------------------------------------------------------------------
-- exposure_stats — computed impact per event x admin boundary (spec.md §6/§7)
-- ---------------------------------------------------------------------------

create table public.exposure_stats (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete restrict,
  admin_boundary_id uuid not null references public.admin_boundaries (id) on delete restrict,
  flooded_area_km2 numeric not null check (flooded_area_km2 >= 0),
  flooded_area_pct numeric not null check (flooded_area_pct between 0 and 100),
  est_population_affected numeric check (est_population_affected is null or est_population_affected >= 0),
  est_buildings_affected int check (est_buildings_affected is null or est_buildings_affected >= 0),
  population_source text,
  building_source text,
  created_at timestamptz not null default now(),
  unique (event_id, admin_boundary_id)
);

comment on table public.exposure_stats is
  'Flooded area/population/building estimates per event x admin boundary — spec.md §6/§7 exposure.compute.';

create index exposure_stats_event_id_idx on public.exposure_stats (event_id);
create index exposure_stats_admin_boundary_id_idx on public.exposure_stats (admin_boundary_id);

alter table public.exposure_stats enable row level security;

-- ---------------------------------------------------------------------------
-- reports — generated PDF reports (spec.md §6/§7)
-- ---------------------------------------------------------------------------

create table public.reports (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete restrict,
  pdf_storage_key text not null,
  generated_at timestamptz not null default now()
);

comment on table public.reports is
  'Generated event PDF reports — spec.md §6/§7 reports.generate. Not unique per event: reports can be regenerated.';

create index reports_event_id_idx on public.reports (event_id);

alter table public.reports enable row level security;

-- ---------------------------------------------------------------------------
-- pipeline_events — insert-only pipeline execution audit log (spec.md §6/§7)
-- ---------------------------------------------------------------------------

create table public.pipeline_events (
  id uuid primary key default gen_random_uuid(),
  -- nullable: aois.list_watched runs with no specific event.
  event_id uuid references public.events (id) on delete restrict,
  -- nullable: only set from inference.run onward, once an inference_runs row exists.
  run_id uuid references public.inference_runs (id) on delete restrict,
  step text not null check (step in (
    'aois.list_watched', 'events.create', 'scenes.fetch', 'preprocess.run',
    'inference.run', 'baseline.diff', 'vectorize.extract', 'exposure.compute',
    'tiles.publish', 'reports.generate'
  )),
  input jsonb,
  output jsonb,
  status text not null check (status in ('success', 'failed')),
  created_at timestamptz not null default now()
);

comment on table public.pipeline_events is
  'Insert-only audit log of every pipeline step''s input/output — spec.md §7 + §13 CLAUDE.md rule. UPDATE/DELETE blocked by trigger.';

create index pipeline_events_event_id_idx on public.pipeline_events (event_id);
create index pipeline_events_run_id_idx on public.pipeline_events (run_id);
create index pipeline_events_step_idx on public.pipeline_events (step);

create trigger pipeline_events_no_update
  before update on public.pipeline_events
  for each row execute function public.pipeline_events_prevent_mutation();

create trigger pipeline_events_no_delete
  before delete on public.pipeline_events
  for each row execute function public.pipeline_events_prevent_mutation();

alter table public.pipeline_events enable row level security;
