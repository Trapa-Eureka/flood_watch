"""Week 3-2: load Philippines ADM4 (barangay) boundaries into admin_boundaries,
flagged is_provisional (spec.md §9: "있는 곳만... '잠정' 표기").

Source: same HDX cod-ab-phl NAMRIA/PSA shapefile bundle used for Week 3-1's
ADM3 load (verified live via CKAN API, not the HDX page's cached text) — its
phl_admin4 layer turned out to cover all 42048 PH barangays nationwide, not a
partial community-sourced set as spec.md's original planning assumption
described (see docs/design-notes.md for the live-verified correction). Kept
is_provisional=True regardless, per spec's intent: barangay boundaries are
finer-grained and subject to more frequent local redistricting/splits than
municipal boundaries, so positional/currency confidence is lower even from
an official source.

Usage:
  python -m tools.load_adm4_boundaries
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from pipeline import config
from pipeline.boundaries import load_boundaries

GEOJSON_PATH = config.DATA_RAW_DIR / "admin_boundaries" / "phl_admin4.geojson"

SOURCE = "HDX cod-ab-phl (NAMRIA/PSA via OCHA FISS) — https://data.humdata.org/dataset/cod-ab-phl"
VINTAGE = "2025-02-13"  # confirmed identical valid_on/version to the ADM3 layer — see design-notes.md


def main():
    n = load_boundaries(
        GEOJSON_PATH, level="adm4_barangay", name_field="adm4_name", pcode_field="adm4_pcode",
        source=SOURCE, vintage=VINTAGE, is_provisional=True,
    )
    print(f"\nDone: {n} adm4_barangay rows loaded.")


if __name__ == "__main__":
    main()
