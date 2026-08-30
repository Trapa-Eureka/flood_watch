"""Week 5-3: formally register the 4 watch_priority river-basin AOIs named in
spec.md §2.1 (Marikina/Cagayan/Bicol-Naga/Pampanga) as real `kind='river_basin',
watch_priority=1` rows in the live aois table.

Status of each going in:
  - Marikina: already done. Week 1-8 (tools/week1_integration_test.py)
    registered it early specifically because "sprint-plan.md Week 5 wants the
    4 watch_priority basins registered anyway" — this script just confirms it
    via the same idempotent get_or_create_aoi() rather than touching it again.
  - Cagayan: a row already exists, but as kind='custom', watch_priority=0 —
    created in Week 5-1 (tools/load_buildings.py's CAGAYAN_BBOX) purely to
    run one backtest event against a Tuguegarao-centered bbox. That bbox has
    now been proven end-to-end through the real production pipeline (Week
    5-1: 72-tile composite, 191 exposure_stats rows, real Modal GPU run) —
    promoted in place (pipeline.repository.promote_aoi) to kind='river_basin',
    watch_priority=1, and renamed to drop the backtest-specific wording, since
    it's the same id an existing completed event already references via
    aoi_id (not name), so nothing downstream breaks.
  - Bicol-Naga, Pampanga: genuinely new. No prior AOI existed for either.
    Bboxes below are NOT guessed from memory — anchored to real Nominatim
    (OpenStreetMap) geocodes fetched live in this session:
      Naga City center:      13.6240, 123.1850
      Bicol River (Minalabac stretch, south of Naga): ~13.52, 123.19
      San Fernando, Pampanga center: 15.0283, 120.6938
      Candaba, Pampanga center:      15.0924, 120.8273
    Each box is sized to comfortably contain the historically flood-prone
    core (Naga City + the Bicol River corridor through Minalabac/Bula/Pili
    for Bicol; San Fernando/Bacolor west to Candaba Swamp/Apalit east for
    Pampanga) at roughly Cagayan's proven scale (~30-38km side) or smaller —
    deliberately not the full literal watershed to the headwaters, since nothing
    larger than Cagayan's 72-tile run has been proven to complete reliably
    (docs/accuracy.md: multi-tile AOI silent partial processing is still an
    open limitation). Bicol ~28x27km, Pampanga ~33x32km — both <= Cagayan's
    ~38x39km.

Idempotent: get_or_create_aoi looks up by name first, promote_aoi is a plain
PATCH by id — safe to re-run.

Usage:
  python -m tools.week5_register_watch_priority_aois
"""
import sys

sys.path.insert(0, ".")
from pipeline import repository

MARIKINA_BBOX = (120.9944, 14.5377, 121.2150, 14.7558)  # already registered (Week 1-8); shown for reference only

# Existing Week 5-1 backtest AOI id, promoted in place rather than duplicated.
CAGAYAN_AOI_ID = "fc84b207-af84-4ff3-bc99-891fe7b0125d"

# (west, south, east, north)
BICOL_NAGA_BBOX = (123.06, 13.47, 123.32, 13.71)
PAMPANGA_BBOX = (120.65, 14.93, 120.96, 15.22)


def main():
    print("=== Marikina (already registered Week 1-8; confirming, not modifying) ===")
    marikina = repository.get_or_create_aoi("Marikina River Basin", "river_basin", MARIKINA_BBOX, watch_priority=1)
    assert marikina["kind"] == "river_basin" and marikina["watch_priority"] == 1, marikina

    print("\n=== Cagayan (promoting existing Week 5-1 backtest AOI in place) ===")
    cagayan = repository.promote_aoi(
        CAGAYAN_AOI_ID, name="Cagayan River Basin", kind="river_basin", watch_priority=1,
    )

    print("\n=== Bicol-Naga (new) ===")
    bicol = repository.get_or_create_aoi("Bicol River Basin (Naga)", "river_basin", BICOL_NAGA_BBOX, watch_priority=1)

    print("\n=== Pampanga (new) ===")
    pampanga = repository.get_or_create_aoi("Pampanga River Basin", "river_basin", PAMPANGA_BBOX, watch_priority=1)

    print("\nDone. watch_priority=1 aois:")
    for aoi in (marikina, cagayan, bicol, pampanga):
        print(f"  {aoi['id']}  {aoi['name']!r}")


if __name__ == "__main__":
    main()
