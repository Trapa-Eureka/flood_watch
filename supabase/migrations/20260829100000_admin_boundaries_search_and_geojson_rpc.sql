-- Home dashboard redesign (2026-08-29, sprint-plan.md 4-5 "홈 대시보드 재설계"):
-- region search box needs to (a) find a boundary by name — down to
-- adm4_barangay level — and (b) fetch ONE selected boundary's actual polygon
-- to draw on the map. Two separate RPCs on purpose: search results are a
-- lightweight list (no geometry — a 42k-row barangay table would make every
-- keystroke's response huge if geom rode along), geometry is fetched only
-- once the user actually picks a result.

-- admin_boundaries has no parent/municipality FK — PSGC codes are
-- hierarchical text instead (adm4's first 9 chars == its adm3 parent's own
-- code, confirmed against real data: barangay "PH0102801001" under
-- municipality "PH0102801"). Resolving parent_name via that prefix match is
-- what makes a bare barangay name ("San Isidro") disambiguable in results.
create or replace function public.search_admin_boundaries(q text, p_limit int default 20)
returns table (
  id uuid,
  name text,
  level text,
  psgc_code text,
  parent_name text
)
language sql stable
as $$
  select ab.id, ab.name, ab.level, ab.psgc_code,
         parent.name as parent_name
  from public.admin_boundaries ab
  left join public.admin_boundaries parent
    on ab.level = 'adm4_barangay'
    and parent.level = 'adm3_municipality'
    and parent.psgc_code = left(ab.psgc_code, 9)
  where ab.name ilike '%' || q || '%'
  order by (ab.level = 'adm3_municipality') desc, ab.name
  limit p_limit
$$;

comment on function public.search_admin_boundaries is
  'Name search across ADM3+ADM4 (ILIKE, no geometry) for the home dashboard region search box — 2026-08-29 redesign.';

create or replace function public.admin_boundary_geojson(p_id uuid)
returns table (id uuid, name text, level text, geojson text)
language sql stable
as $$
  select ab.id, ab.name, ab.level, extensions.st_asgeojson(ab.geom) as geojson
  from public.admin_boundaries ab
  where ab.id = p_id
$$;

comment on function public.admin_boundary_geojson is
  'Single boundary polygon as GeoJSON text, fetched only after a search result is picked — 2026-08-29 home dashboard redesign.';
