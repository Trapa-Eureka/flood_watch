-- Week4-6 admin trigger UI (docs/sprint-plan.md): given an event_id, resolve
-- everything the Python pipeline orchestrator (pipeline/orchestrator.py)
-- needs to actually run it — the AOI's bbox and the event's own dates. Every
-- prior real pipeline run in this project (Week1-8 onward) got its bbox from
-- a hardcoded config.AOI_BBOX or a script literal; this is the first time an
-- ARBITRARY user-drawn AOI needs its bbox resolved generically from the DB.
--
-- aois.geom is stored as an axis-aligned rectangle (repository.py's
-- _bbox_to_wkt_polygon — the admin UI only ever draws rectangles, Week4-2's
-- own documented reason), so ST_XMin/XMax/YMin/YMax on it recovers exactly
-- that original bbox, not an approximation of some other shape.
create or replace function public.event_aoi_bbox(p_event_id uuid)
returns table (
  event_id uuid, name text, status text,
  pre_event_date date, post_event_date date,
  west double precision, south double precision, east double precision, north double precision
)
language sql stable
as $$
  select e.id, e.name, e.status, e.pre_event_date, e.post_event_date,
         extensions.st_xmin(a.geom), extensions.st_ymin(a.geom),
         extensions.st_xmax(a.geom), extensions.st_ymax(a.geom)
  from public.events e
  join public.aois a on a.id = e.aoi_id
  where e.id = p_event_id
$$;

comment on function public.event_aoi_bbox is
  'events + its AOI bbox, resolved for pipeline/orchestrator.py (Week4-6). Called with the service_role key only in practice, same as every other pipeline write path in this project.';
