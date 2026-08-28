"""Week 1-8: the actual integration test — event registration -> STAC
collection -> preprocessing, with every step's input/output landing in the
live DB (spec.md §7's pipeline_events audit trail) and the resolved AOI/event/
scene_refs rows persisted as real (not throwaway) data.

Deliberately NOT a throwaway test: this registers the Marikina river basin as
a real watch_priority AOI and the Kristine/Trami 2024-10 event as a real
backtest event — both genuinely useful beyond just "does the wiring work"
(sprint-plan.md Week 5 wants the 4 watch_priority basins registered anyway;
this is the first of them, done early because it doubles as this test's
subject). get_or_create_aoi/record_scene_ref are idempotent, so re-running
this script is safe.

Intentionally stops after preprocess.run — inference.run/baseline.diff don't
exist yet (Week 2). events.status is left at 'processing', not 'completed'.

Usage:
  python -m tools.week1_integration_test
"""
from pipeline import config
from pipeline.db import pipeline_step
from pipeline.preprocess import s2_composite
from pipeline.repository import create_event, get_or_create_aoi, record_scene_ref, update_event_status
from pipeline.stac_client import fetch_best_s2_scenes, upload_raw_scene_to_r2


def main() -> int:
    bbox = tuple(config.AOI_BBOX)

    print("=== 1) aois.list_watched (register Marikina as a real watch_priority AOI) ===")
    with pipeline_step("aois.list_watched", input={"name": "Marikina River Basin"}) as step:
        aoi = get_or_create_aoi("Marikina River Basin", "river_basin", bbox, watch_priority=1)
        step.output = {"aoi_id": aoi["id"]}

    print("\n=== 2) events.create (Kristine/Trami 2024-10 backtest) ===")
    with pipeline_step("events.create", input={"aoi_id": aoi["id"]}) as step:
        event = create_event(
            aoi_id=aoi["id"], name="Kristine (Trami) 2024-10 backtest", kind="backtest",
            pre_event_date=config.PRE_EVENT_START, post_event_date=config.POST_EVENT_END,
        )
        step.output = {"event_id": event["id"]}
    event_id = event["id"]
    update_event_status(event_id, "processing")

    print("\n=== 3) scenes.fetch (S2 candidate search + AOI-local cloud selection) ===")
    with pipeline_step("scenes.fetch", event_id=event_id, input={"bbox": list(bbox)}) as step:
        selection = fetch_best_s2_scenes(
            bbox, config.PRE_EVENT_START, config.PRE_EVENT_END,
            config.POST_EVENT_START, config.POST_EVENT_END,
        )
        recorded = {}
        for role, result in selection.items():
            if result is None or result["item"] is None:
                print(f"  {role}: no candidate found — not recorded")
                continue
            item = result["item"]
            band_paths = None
            storage_key = None
            if role == "post_event":
                # Only post_event actually gets composited/used downstream in
                # this architecture (baseline comes from JRC, not a 2nd S2
                # composite — see docs/design-notes.md Week 1-2/A-2) — but we
                # still record scene_refs for whatever was found in both roles
                # for the audit trail; only post_event gets its bands
                # downloaded here since that's the only one preprocess.run needs.
                band_paths = s2_composite.download_all_bands(item, config.DATA_RAW_DIR / "s2_bands")
                try:
                    uploaded = upload_raw_scene_to_r2(item, band_paths)
                    storage_key = uploaded.get("BLUE")  # representative key; all 6 share the item.id/ prefix
                except RuntimeError as e:
                    print(f"  ! R2 upload skipped (Week 1-4 credentials not set yet): {e}")

            scene_ref = record_scene_ref(event_id, item, role, storage_key=storage_key)
            recorded[role] = {"scene_ref_id": scene_ref["id"], "stac_id": item.id,
                               "local_cloud_pct": result["local_cloud_pct"], "ok": result["ok"]}
        step.output = recorded

    post_event_item = None
    if selection.get("post_event") and selection["post_event"]["item"] is not None:
        post_event_item = selection["post_event"]["item"]

    if post_event_item is None:
        print("\nNo post_event scene found at all — cannot run preprocess.run. Stopping here.")
        update_event_status(event_id, "failed")
        return 1

    print("\n=== 4) preprocess.run (build the 6-band composite for inference.run, Week 2) ===")
    with pipeline_step("preprocess.run", event_id=event_id, input={"stac_id": post_event_item.id}) as step:
        result = s2_composite.preprocess_scene(post_event_item, bbox, pad_ratio=0.05)
        step.output = {"composite_path": str(result["composite_path"])}

    print(f"\n=== Week 1-8 integration test complete ===")
    print(f"event_id={event_id}  aoi_id={aoi['id']}  composite={result['composite_path']}")
    print("events.status left at 'processing' — inference.run/baseline.diff are Week 2, not done yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
