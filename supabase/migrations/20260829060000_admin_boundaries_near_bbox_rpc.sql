-- spec.md §7 vectorize.extract "육지 클립"(Week 3-5): vectorize.py needs the
-- land boundary near a specific event's AOI to clip spurious offshore/sea
-- polygon fragments out of the flood polygon. Fetching all 1642 ADM3 rows
-- (17.5MB) per event would work but is wasteful when a typical event AOI
-- only touches a handful of municipalities — this RPC uses the existing
-- admin_boundaries_geom_gix GIST index (see initial_schema.sql) to filter
-- server-side instead.
create or replace function public.admin_boundaries_near_bbox(
  west double precision, south double precision, east double precision, north double precision,
  p_level text default 'adm3_municipality'
) returns setof public.admin_boundaries
language sql stable
as $$
  select ab.* from public.admin_boundaries ab
  where ab.level = p_level
    and ab.geom && extensions.st_makeenvelope(west, south, east, north, 4326)
$$;

comment on function public.admin_boundaries_near_bbox is
  'Bbox-filtered admin_boundaries fetch (uses admin_boundaries_geom_gix) — spec.md §7 vectorize.extract land-clip, Week 3-5. Also reusable by Week 3-6 exposure.compute.';
