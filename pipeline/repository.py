"""Thin data-access layer for the "business" tables (aois/events/scene_refs/
inference_runs) — Week 1-8 + Week 2-6. Deliberately separate from pipeline/db.py, which only ever writes
the insert-only pipeline_events audit log: these tables are mutable business
data (an event's status changes, a scene_ref's storage_key fills in later),
so they get ordinary CRUD-ish helpers instead of pipeline_events' append-only
contract.

Same reasoning as pipeline/db.py for *how* it talks to Postgres: plain
`requests` against Supabase's PostgREST REST API with the service_role key
(bypasses RLS — this is backend-only code), not supabase-py/psycopg2.
"""
import os
from typing import Optional

import requests

from pipeline import config

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def _headers(prefer: str = "return=representation") -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not found in .env — see .env.example.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _bbox_to_wkt_polygon(bbox) -> str:
    west, south, east, north = bbox
    return (
        f"POLYGON(({west} {south}, {east} {south}, {east} {north}, "
        f"{west} {north}, {west} {south}))"
    )


def _check(resp: requests.Response, what: str):
    if resp.status_code >= 400:
        raise RuntimeError(f"{what} failed ({resp.status_code}): {resp.text}")


# ---------------------------------------------------------------------------
# aois
# ---------------------------------------------------------------------------

def get_or_create_aoi(name: str, kind: str, bbox, watch_priority: int = 0) -> dict:
    """Idempotent by name (aois has no unique constraint on it, but this
    script is expected to be re-run during Week 1 testing/debugging — no
    reason to accumulate duplicate 'Marikina River Basin' rows)."""
    url = f"{config.SUPABASE_URL}/rest/v1/aois"
    existing = requests.get(url, headers=_headers(), params={"name": f"eq.{name}", "select": "*"}, timeout=30)
    _check(existing, "aois lookup")
    rows = existing.json()
    if rows:
        print(f"  aois: found existing {name!r} (id={rows[0]['id']})")
        return rows[0]

    body = {"name": name, "kind": kind, "geom": _bbox_to_wkt_polygon(bbox), "watch_priority": watch_priority}
    resp = requests.post(url, headers=_headers(), json=body, timeout=30)
    _check(resp, "aois insert")
    row = resp.json()[0]
    print(f"  aois: created {name!r} (id={row['id']})")
    return row


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

def create_event(aoi_id: str, name: str, kind: str, pre_event_date: str,
                  post_event_date: Optional[str] = None, status: str = "registered") -> dict:
    url = f"{config.SUPABASE_URL}/rest/v1/events"
    body = {
        "aoi_id": aoi_id, "name": name, "kind": kind,
        "pre_event_date": pre_event_date, "post_event_date": post_event_date, "status": status,
    }
    resp = requests.post(url, headers=_headers(), json=body, timeout=30)
    _check(resp, "events insert")
    row = resp.json()[0]
    print(f"  events: created {name!r} (id={row['id']}, status={row['status']})")
    return row


def update_event_status(event_id: str, status: str) -> dict:
    url = f"{config.SUPABASE_URL}/rest/v1/events"
    resp = requests.patch(url, headers=_headers(), params={"id": f"eq.{event_id}"}, json={"status": status}, timeout=30)
    _check(resp, "events status update")
    row = resp.json()[0]
    print(f"  events: {event_id} -> status={status}")
    return row


# ---------------------------------------------------------------------------
# scene_refs
# ---------------------------------------------------------------------------

def record_scene_ref(event_id: str, item, role: str, storage_key: Optional[str] = None) -> dict:
    """Record a resolved STAC item against an event. Idempotent on
    (event_id, stac_id) — the schema's own unique constraint — a re-run that
    hits an existing row updates storage_key instead of erroring."""
    url = f"{config.SUPABASE_URL}/rest/v1/scene_refs"
    body = {
        "event_id": event_id, "stac_id": item.id, "collection": config.SENTINEL2_COLLECTION,
        "role": role, "acquired_at": str(item.datetime), "footprint": _bbox_to_wkt_polygon(item.bbox),
        "storage_key": storage_key,
    }
    resp = requests.post(
        url, headers={**_headers(), "Prefer": "return=representation,resolution=merge-duplicates"},
        params={"on_conflict": "event_id,stac_id"}, json=body, timeout=30,
    )
    _check(resp, "scene_refs upsert")
    row = resp.json()[0]
    print(f"  scene_refs: {role} = {item.id} (id={row['id']}, storage_key={row['storage_key']})")
    return row


# ---------------------------------------------------------------------------
# inference_runs
# ---------------------------------------------------------------------------

def create_inference_run(event_id: str, model: str, model_version: Optional[str] = None,
                          input_scene_ids: Optional[list] = None, status: str = "running") -> dict:
    """input_scene_ids is a plain list (STAC ids or scene_refs uuids — caller's
    choice, this table just stores whatever jsonb it's given, see spec.md §6).
    Default status='running': in this pipeline inference.run is invoked
    synchronously and awaited (no separate job queue yet), so by the time
    Python code exists to call this, inference has already started — 'pending'
    would only apply to an async/queued design this project doesn't have."""
    url = f"{config.SUPABASE_URL}/rest/v1/inference_runs"
    body = {
        "event_id": event_id, "model": model, "model_version": model_version,
        "input_scene_ids": input_scene_ids or [], "status": status,
    }
    resp = requests.post(url, headers=_headers(), json=body, timeout=30)
    _check(resp, "inference_runs insert")
    row = resp.json()[0]
    print(f"  inference_runs: created (id={row['id']}, model={model}, status={status})")
    return row


def update_inference_run(run_id: str, status: str, finished_at: Optional[str] = None,
                          metrics: Optional[dict] = None) -> dict:
    """finished_at defaults to "now" via Postgres's own now() if not passed —
    simplest to just always pass it explicitly from the caller (it knows the
    real completion time better than a second network round-trip would)."""
    import datetime as _dt

    url = f"{config.SUPABASE_URL}/rest/v1/inference_runs"
    body = {
        "status": status,
        "finished_at": finished_at or _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "metrics": metrics or {},
    }
    resp = requests.patch(url, headers=_headers(), params={"id": f"eq.{run_id}"}, json=body, timeout=30)
    _check(resp, "inference_runs update")
    row = resp.json()[0]
    print(f"  inference_runs: {run_id} -> status={status}")
    return row


# ---------------------------------------------------------------------------
# flood_extents
# ---------------------------------------------------------------------------

def create_flood_extent(event_id: str, run_id: str, geom_wkt: str, area_km2: float,
                         confidence_mean: Optional[float] = None,
                         raster_storage_key: Optional[str] = None) -> dict:
    """raster_storage_key is nullable (Week 2-7 migration) — R2 upload is a
    separate step that may not have happened yet (or, right now, R2
    credentials from Week 1-4 may not even be set), so this can be filled in
    later with a follow-up PATCH once the raster is actually in R2."""
    url = f"{config.SUPABASE_URL}/rest/v1/flood_extents"
    body = {
        "event_id": event_id, "run_id": run_id, "geom": geom_wkt, "area_km2": area_km2,
        "confidence_mean": confidence_mean, "raster_storage_key": raster_storage_key,
    }
    resp = requests.post(url, headers=_headers(), json=body, timeout=30)
    _check(resp, "flood_extents insert")
    row = resp.json()[0]
    print(f"  flood_extents: created (id={row['id']}, area_km2={area_km2:.4f})")
    return row


# ---------------------------------------------------------------------------
# exposure_stats
# ---------------------------------------------------------------------------

def upsert_exposure_stat(event_id: str, admin_boundary_id: str, flooded_area_km2: float,
                          flooded_area_pct: float, est_population_affected: Optional[float] = None,
                          est_buildings_affected: Optional[int] = None,
                          population_source: Optional[str] = None,
                          building_source: Optional[str] = None) -> dict:
    """Idempotent on (event_id, admin_boundary_id) — the schema's own unique
    constraint (same reasoning as scene_refs' upsert: exposure.compute may be
    re-run for the same event, e.g. after a bug fix, and should replace the
    old numbers rather than error or duplicate)."""
    url = f"{config.SUPABASE_URL}/rest/v1/exposure_stats"
    body = {
        "event_id": event_id, "admin_boundary_id": admin_boundary_id,
        "flooded_area_km2": flooded_area_km2, "flooded_area_pct": flooded_area_pct,
        "est_population_affected": est_population_affected,
        "est_buildings_affected": est_buildings_affected,
        "population_source": population_source, "building_source": building_source,
    }
    resp = requests.post(
        url, headers={**_headers(), "Prefer": "return=representation,resolution=merge-duplicates"},
        params={"on_conflict": "event_id,admin_boundary_id"}, json=body, timeout=30,
    )
    _check(resp, "exposure_stats upsert")
    row = resp.json()[0]
    print(f"  exposure_stats: admin_boundary_id={admin_boundary_id} flooded_area_km2={flooded_area_km2:.4f} "
          f"({flooded_area_pct:.2f}%) pop={est_population_affected} buildings={est_buildings_affected}")
    return row
