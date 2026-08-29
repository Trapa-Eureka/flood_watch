# PH Flood Watch — web (Next.js + MapLibre dashboard)

Week 4-1 scaffold: a full-viewport MapLibre map centered on the whole
Philippines, no data layers yet (that starts at 4-2: AOI/event registration
UI). Next.js 15 (App Router) + React 19 + TypeScript, MapLibre GL 4.7.1.

## Reused from PH Fuel Watch (`/Volumes/T7/work/oil`, package.json name
`ph-fuel-watch`) — spec.md §5's explicit "Fuel Watch 재사용 패턴" instruction:

- **`next.config.ts`**: dev cache set to in-memory only (both webpack's and
  Turbopack's persistent filesystem caches misbehave on this exFAT drive —
  Fuel Watch's own `next.config.mjs` documents the exact failure mode) + a
  CSP header block with the specific allowances MapLibre needs
  (`wasm-unsafe-eval`, `blob:` workers) and Next's own inline hydration
  scripts need (`'unsafe-inline'` in `script-src` — a known separate gotcha,
  not MapLibre-specific).
- **Basemap**: [OpenFreeMap](https://openfreemap.org) `liberty` style — free,
  no API key, already vetted in production by Fuel Watch.
- **`MapView.tsx`**: the self-healing style-reload retry (OpenFreeMap is a
  best-effort free host; an intermittent failed style fetch otherwise leaves
  a permanently blank map) and the `styleimagemissing` → blank-pixel fix,
  ported near-verbatim from Fuel Watch's `map-logic.js` and adapted to a
  React `useEffect` lifecycle (Fuel Watch's version is vanilla imperative JS,
  not a React component).
- `tsconfig.json`: same non-strict config (`strict: false`, `@/*` path alias).

**Not reused**: Fuel Watch's actual map *content* (price chips, station pins,
brand badges, bottom sheet, area search) — that's fuel-price-specific UI: not
usable here as-is. This project's own data layers (AOI drawing, event list,
before/after imagery, flood overlay, exposure stats) come from 4-2 onward.

## Run

```sh
cd web
npm install
npm run dev
# open http://localhost:3000
```

No `.env.local` needed yet (see `.env.local.example` — wired up starting 4-2).
