"""Week 3-8: tiles.publish, exercised two ways —

1. The real Marikina Kristine/Trami event (Week 1-8's actual event_id/scene_refs):
   builds+writes a POST-event RGB COG and a flood-overlay COG against the real
   DB rows. No "pre" tile here — Week 1-8 honestly recorded the baseline scene
   as not meeting the local-cloud-cover bar (scene_refs.role='baseline' exists
   but no composite was ever built from it), so publish_event_tiles legitimately
   returns pre=None for this event; not a test gap, a real data limitation.

2. A genuine pre/post PAIR (data/output/event2_pre_20250615.tif /
   event2_post_20250804.tif, leftover from spike-era exploration of a second
   backtest candidate — no registered `events` row for it yet, that's Week
   5-1's job, "과거 이벤트 프로덕션 재실행") — demonstrates the actual
   "전후 타일 페어" case spec.md asks for, without DB writes.

Usage:
  python -m tools.week3_tiles_test
"""
import os
import sys

import requests

sys.path.insert(0, ".")
from pipeline import config, repository
from pipeline.tiles import publish_event_tiles

EVENT_ID = "71426a18-da5c-4a99-a527-1600a32ea24e"
POST_SCENE_REF_ID = "a02cde2b-3031-40f8-be5d-6ef90320b0ab"
POST_COMPOSITE = "data/output/S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159_composite.tif"
FLOOD_RASTER = "data/output/S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159_new_flood_w27.tiff"

PAIR_PRE = "data/output/event2_pre_20250615.tif"
PAIR_POST = "data/output/event2_post_20250804.tif"


def cog_is_valid(path) -> bool:
    from rio_cogeo.cogeo import cog_validate

    ok, errors, warnings = cog_validate(path)
    if warnings:
        print(f"    cog_validate warnings for {path}: {warnings}")
    if not ok:
        print(f"    cog_validate ERRORS for {path}: {errors}")
    return ok


def main():
    print("=== 1. Real Marikina event (post + flood only, real DB writes) ===")
    result = publish_event_tiles(
        EVENT_ID, pre_composite_path=None, post_composite_path=POST_COMPOSITE,
        flood_raster_path=FLOOD_RASTER,
    )
    for label, r in result.items():
        if r:
            print(f"  {label}: valid_cog={cog_is_valid(r['local_path'])}")
        else:
            print(f"  {label}: None (no source raster for this event)")

    if result["post"]:
        repository.update_scene_ref_cog(POST_SCENE_REF_ID, result["post"]["r2_key"])

    print("\n=== 2. Real pre/post PAIR (event2, COG-build only, no DB event yet) ===")
    pair_result = publish_event_tiles(
        "event2-demo", pre_composite_path=PAIR_PRE, post_composite_path=PAIR_POST,
    )
    for label, r in pair_result.items():
        if r:
            print(f"  {label}: valid_cog={cog_is_valid(r['local_path'])}")
        else:
            print(f"  {label}: None")


if __name__ == "__main__":
    main()
