# PH Flood Watch

**Near real-time flood mapping for the Philippines, powered by satellite imagery.**

## Overview

PH Flood Watch turns satellite observations into a clear picture of where flooding happened, how large the affected area is, and how many people and buildings were likely impacted — within hours of a typhoon or monsoon event, not days.

The Philippines is hit by tropical storms year after year. Existing flood systems focus on forecasting risk *before* a storm arrives. PH Flood Watch fills the gap that comes *after*: confirming actual flood extent once the storm has passed, using the same satellites that watch the whole country continuously and for free.

## Status

Weeks 1–4 of a 5-week build are complete and running against live data: automated Sentinel-2 collection, cloud masking, Prithvi-EO-2.0 flood inference on serverless GPU, JRC baseline differencing, exposure statistics (population/buildings per municipality), an authenticated dashboard, and PDF reporting. Week 5 (historical backtesting, honest accuracy documentation, expanding to 4 priority river basins, and this open-source split) is in progress.

## Repository layout — open core vs. private product

This repo intentionally mixes two things with two different licenses, kept in separate parts of the tree:

| | Path | License |
|---|---|---|
| **Open — reusable satellite flood-mapping pipeline** | [`pipeline/`](pipeline/) *(excluding the 5 files below)* | [MIT](pipeline/LICENSE) |
| Vendored model inference code | [`pipeline/inference/prithvi_inference.py`](pipeline/inference/prithvi_inference.py) | Apache-2.0 (IBM/NASA-IMPACT, unmodified — see file header) |
| **Private — this project's product** | `pipeline/db.py`, `pipeline/repository.py`, `pipeline/orchestrator.py`, `pipeline/reports.py`, `pipeline/tiles.py`, [`web/`](web/), [`workers/`](workers/), [`supabase/`](supabase/) | All rights reserved (no license granted) |

The split follows what's actually reusable outside this specific product: given an AOI and a date range, the open pipeline collects Sentinel-2 imagery, masks clouds, runs Prithvi-EO-2.0 + the sen1floods11 checkpoint to get a flood-probability raster, differences it against the JRC Global Surface Water baseline to isolate *new* flooding, vectorizes it, and (optionally) overlays it against administrative boundaries + WorldPop + building footprints to estimate population/building exposure. None of that depends on this project's own database, hosting, or business logic — so it's MIT-licensed and meant to be reused (e.g. for other flood-prone regions, or other STAC-based satellite-inference tasks). The dashboard, auth, PDF report generator, tile publishing, and the event/AOI database layer that drives them are this project's actual product and stay closed, even though (for now) they're visible in this same public repository — visibility and license are not the same thing; nothing outside `pipeline/`'s MIT-covered files is licensed for reuse.

## The open pipeline: what it does

```
AOI (bbox) + event dates
  → STAC search (Copernicus Data Space Ecosystem) — Sentinel-2 L2A, best pre/post scenes by AOI-local cloud cover
  → preprocessing — reprojection, tiling, cloud mask (SCL band)
  → Prithvi-EO-2.0 + sen1floods11 inference (TerraTorch), on Modal serverless GPU
  → differencing against JRC Global Surface Water (permanent-water baseline) → new-flood raster
  → vectorization → flood extent polygon (GeoJSON)
  → (optional) overlay against admin boundaries + WorldPop population + building footprints → exposure stats
```

Every step above is a real, independently callable Python module under [`pipeline/`](pipeline/) — see each file's own docstring for the specifics and the tradeoffs made along the way.

### Running it standalone

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # only CDSE_USERNAME/CDSE_PASSWORD (free, dataspace.copernicus.eu) + HF_TOKEN
                        # (Hugging Face, for the Prithvi checkpoint) are needed for the pipeline alone —
                        # the SUPABASE_*/R2_*/MODAL_* vars are only for this project's own product layer.
```

From there, `pipeline.stac_client`, `pipeline.preprocess`, `pipeline.inference`, `pipeline.baseline_diff`, `pipeline.vectorize`, and `pipeline.exposure` are usable as a library against any AOI — `tools/week1_integration_test.py` is a real, working end-to-end example (STAC search through preprocessing) to read for the calling pattern.

## The product: dashboard, reports, monitoring

On top of the open pipeline, this project runs a hosted product: an authenticated Next.js + MapLibre dashboard (event registration, before/after comparison, flood overlay, exposure statistics), PDF report generation, and role-gated access (admin / LGU-DRRMO-and-NGO viewer / public) backed by Supabase (PostGIS + RLS) and Cloudflare R2. That layer — everything in `web/`, `workers/`, `supabase/`, plus the five business-glue files in `pipeline/` listed above — is not open source.

## Why it matters

- **Faster ground truth.** Flood extent is estimated directly from satellite data shortly after each event, instead of waiting on manual damage assessment.
- **Consistent coverage.** The same method applies to every watched river basin, every event — no dependence on which areas happen to get reported on.
- **Built for the places that need it most.** Starting with river basins that flood repeatedly and affect large populations: Marikina, Cagayan, Bicol/Naga, and Pampanga.
- **Numbers, not just maps.** Flooded area, affected population, and affected buildings are calculated per municipality, so responders can prioritize where to act first.

## A note on accuracy

Every map and report is clearly labeled as an **AI-generated estimate**, not an official hazard determination, and carries the required "Contains modified Copernicus Sentinel data" attribution. It is meant to complement, not replace, official information from PAGASA and local government units — always check official channels for authoritative guidance during an actual emergency. This project also tracks its own known accuracy limitations honestly as part of its development process (e.g. how much of the detected "new flooding" can and can't be explained by the water-baseline's 30m resolution) — that isn't published in this repo yet, but nothing here claims a precision the method doesn't have.

---

*Contains modified Copernicus Sentinel data.*
