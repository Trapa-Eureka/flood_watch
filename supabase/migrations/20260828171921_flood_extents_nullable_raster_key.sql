-- Week 2-7: flood_extents.raster_storage_key was NOT NULL in the 1-2 sketch,
-- but that assumes the raster is always uploaded to R2 before the row is
-- inserted. In practice (same situation as scene_refs.storage_key, made
-- nullable back in 1-2 for the same reason): R2 credentials are a manual
-- Cloudflare-dashboard step (Week 1-4, still pending as of this migration),
-- and even once they exist, a real async pipeline computes the extent and
-- inserts the row before/independently of the raster upload finishing.
-- Nullable now, filled in by a later UPDATE once the raster is actually in R2.

alter table public.flood_extents
  alter column raster_storage_key drop not null;
