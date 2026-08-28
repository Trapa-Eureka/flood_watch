"""Week 3-1: load Philippines ADM3 (city/municipality) boundaries into
admin_boundaries. Source verified against the live file (not the HDX page's
own summary text, which can be stale — see docs/design-notes.md's existing
memory-documented lesson on this) via `ogr2ogr`/GDAL's /vsizip/vsicurl/,
reading only the phl_admin3 layer out of the combined multi-level HDX zip
without downloading the whole archive.

Usage:
  python -m tools.load_adm3_boundaries
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from pipeline import config
from pipeline.boundaries import load_boundaries

GEOJSON_PATH = config.DATA_RAW_DIR / "admin_boundaries" / "phl_admin3.geojson"

# Source: HDX cod-ab-phl (OCHA FISS, sourced from NAMRIA/PSA), verified live
# via the HDX CKAN API (not the page's cached summary text) on 2026-08-29.
SOURCE = "HDX cod-ab-phl (NAMRIA/PSA via OCHA FISS) — https://data.humdata.org/dataset/cod-ab-phl"
# Every one of the 1642 features carries the identical valid_on=2025-02-13,
# version=v03 — a genuinely consistent vintage, not an assumption.
VINTAGE = "2025-02-13"


def main():
    n = load_boundaries(
        GEOJSON_PATH, level="adm3_municipality", name_field="adm3_name", pcode_field="adm3_pcode",
        source=SOURCE, vintage=VINTAGE,
    )
    print(f"\nDone: {n} adm3_municipality rows loaded.")


if __name__ == "__main__":
    main()
