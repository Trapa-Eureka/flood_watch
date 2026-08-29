-- spec.md §7 tiles.publish (Week 3-8): scene_refs.storage_key already holds
-- the raw archived scene (Week 1-5), a separate artifact from the web-ready
-- RGB quicklook COG tiles.publish produces for the dashboard's pre/post
-- comparison slider — needs its own nullable column, same pattern as
-- flood_extents.raster_storage_key (nullable since R2 credentials aren't
-- always available yet, see docs/design-notes.md).
alter table public.scene_refs
  add column cog_storage_key text;

comment on column public.scene_refs.cog_storage_key is
  'R2 key for the web-optimized RGB quicklook COG (ph-flood-watch-tiles bucket) — spec.md §7 tiles.publish, Week 3-8. Distinct from storage_key (the raw archived scene, ph-flood-watch-raw bucket).';
