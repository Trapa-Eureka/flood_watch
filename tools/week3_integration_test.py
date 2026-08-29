"""Week 3-9: Week 3 통합 테스트 — vectorize.extract -> exposure.compute ->
tiles.publish, run as ONE continuous, pipeline_events-audited chain against
the real Marikina Kristine/Trami event (same event_id/run_id used since
Week 1-8/2-7).

Why this is worth doing even though 3-5/3-6/3-8 already individually verified
each step against real data: none of those ad-hoc test scripts wrapped their
calls in pipeline_step() — pipeline_events (Week 1-2/1-7's insert-only audit
log) has ZERO rows for vectorize.extract/exposure.compute/tiles.publish
despite all three having already written real results to the DB. That's a
real gap in this project's own "재현 불가능한 추론 실행 금지" rule (spec.md
§13) — this script closes it, not just re-confirms numbers already confirmed.

All three repository writes below are idempotent (upsert or PATCH-by-id), so
re-running this against the same event is always safe.

Usage:
  python -m tools.week3_integration_test
"""
import os
import sys

import requests

sys.path.insert(0, ".")
from pipeline import config, repository
from pipeline.db import pipeline_step
from pipeline.exposure import compute_exposure_stats
from pipeline.tiles import publish_event_tiles
from pipeline.vectorize import vectorize_new_flood

EVENT_ID = "71426a18-da5c-4a99-a527-1600a32ea24e"  # Kristine/Trami, since Week 1-8
RUN_ID = "38c8c464-b480-4ef1-addf-5378f13a28ab"  # inference_runs row, since Week 2-6/2-7
POST_SCENE_REF_ID = "a02cde2b-3031-40f8-be5d-6ef90320b0ab"

FLOOD_RASTER = "data/output/S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159_new_flood_w27.tiff"
POST_COMPOSITE = "data/output/S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159_composite.tif"


def _headers():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def main():
    # --- vectorize.extract ---------------------------------------------
    # flood_extents has no upsert key (Week 2-7's repository.create_flood_extent
    # always INSERTs) — this integration test recomputes vectorize_new_flood
    # fresh and PATCHes the existing row in place (same row Week 3-5 already
    # updated) instead of inserting a duplicate for the same event+run. A
    # side benefit: this doubles as a reproducibility check — the recomputed
    # value should exactly match what's already stored.
    with pipeline_step("vectorize.extract", event_id=EVENT_ID, run_id=RUN_ID,
                        input={"raster": FLOOD_RASTER}) as step:
        vec = vectorize_new_flood(FLOOD_RASTER)
        assert vec is not None, "expected real new-flood area for this event"
        resp = requests.get(
            f"{config.SUPABASE_URL}/rest/v1/flood_extents",
            headers=_headers(), params={"event_id": f"eq.{EVENT_ID}", "select": "id,area_km2"}, timeout=30,
        )
        resp.raise_for_status()
        existing = resp.json()[0]
        reproduced = round(vec["area_km2"], 4) == round(float(existing["area_km2"]), 4)
        print(f"  recomputed area_km2={vec['area_km2']} vs stored={existing['area_km2']} "
              f"(reproducible: {reproduced})")
        patch = requests.patch(
            f"{config.SUPABASE_URL}/rest/v1/flood_extents",
            headers={**_headers(), "Content-Type": "application/json", "Prefer": "return=representation"},
            params={"id": f"eq.{existing['id']}"},
            json={"geom": vec["geom_wkt"], "area_km2": vec["area_km2"]}, timeout=30,
        )
        patch.raise_for_status()
        flood_row = patch.json()[0]
        step.output = {"flood_extent_id": flood_row["id"], "area_km2": vec["area_km2"], "reproduced_prior_value": reproduced}
        print(f"vectorize.extract: area_km2={vec['area_km2']}")

    from shapely.geometry import shape
    flood_geom_wkt = shape(flood_row["geom"]).wkt

    # --- exposure.compute -------------------------------------------------
    with pipeline_step("exposure.compute", event_id=EVENT_ID, run_id=RUN_ID,
                        input={"flood_extent_id": flood_row["id"]}) as step:
        adm3 = compute_exposure_stats(flood_geom_wkt, level="adm3_municipality")
        adm4 = compute_exposure_stats(flood_geom_wkt, level="adm4_barangay")
        for s in adm3 + adm4:
            repository.upsert_exposure_stat(
                event_id=EVENT_ID, admin_boundary_id=s["admin_boundary_id"],
                flooded_area_km2=s["flooded_area_km2"], flooded_area_pct=s["flooded_area_pct"],
                est_population_affected=s["est_population_affected"],
                est_buildings_affected=s["est_buildings_affected"],
                population_source=s["population_source"], building_source=s["building_source"],
            )
        step.output = {
            "adm3_count": len(adm3), "adm4_count": len(adm4),
            "adm3_total_km2": round(sum(s["flooded_area_km2"] for s in adm3), 4),
            "total_population": sum(s["est_population_affected"] or 0 for s in adm3),
            "total_buildings": sum(s["est_buildings_affected"] or 0 for s in adm3),
        }
        print(f"exposure.compute: {step.output}")

    # --- tiles.publish ------------------------------------------------------
    with pipeline_step("tiles.publish", event_id=EVENT_ID, run_id=RUN_ID,
                        input={"post_composite": POST_COMPOSITE, "flood_raster": FLOOD_RASTER}) as step:
        tiles = publish_event_tiles(
            EVENT_ID, pre_composite_path=None, post_composite_path=POST_COMPOSITE,
            flood_raster_path=FLOOD_RASTER,
        )
        if tiles["post"]:
            repository.update_scene_ref_cog(POST_SCENE_REF_ID, tiles["post"]["r2_key"])
        step.output = {k: (v is not None) for k, v in tiles.items()}
        print(f"tiles.publish: built={step.output}")

    # --- final consolidated report (real DB read-back, not just in-memory) --
    print("\n=== Week 3 통합 테스트 최종 요약 (실제 DB 재조회) ===")
    resp = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/pipeline_events",
        headers=_headers(),
        params={"event_id": f"eq.{EVENT_ID}", "step": "in.(vectorize.extract,exposure.compute,tiles.publish)",
                "select": "step,status,created_at", "order": "created_at.desc", "limit": "3"},
        timeout=30,
    )
    print("pipeline_events (최신 3건):")
    for row in resp.json():
        print(f"  {row['step']}: {row['status']} @ {row['created_at']}")

    resp = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/exposure_stats",
        headers=_headers(),
        params={"event_id": f"eq.{EVENT_ID}", "select": "flooded_area_km2,est_population_affected,est_buildings_affected"},
        timeout=30,
    )
    stats = resp.json()
    print(f"exposure_stats: {len(stats)} rows, "
          f"total_pop={sum(s['est_population_affected'] or 0 for s in stats)}, "
          f"total_buildings={sum(s['est_buildings_affected'] or 0 for s in stats)}")


if __name__ == "__main__":
    main()
