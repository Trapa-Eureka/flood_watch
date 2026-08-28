-- spec.md §9 Week 3-2: ADM4(barangay) boundaries are loaded "있는 곳만" and
-- flagged "잠정"(provisional) — community/finer-grained data carries more
-- positional-accuracy uncertainty than ADM3, so exposure.compute (Week 3-6)
-- must be able to tell the two levels apart even though both share one table.
alter table public.admin_boundaries
  add column is_provisional boolean not null default false;

comment on column public.admin_boundaries.is_provisional is
  'true for boundaries loaded with lower confidence in positional accuracy/currency (spec.md §9 Week 3-2: ADM4 barangay). ADM3 rows stay false.';
