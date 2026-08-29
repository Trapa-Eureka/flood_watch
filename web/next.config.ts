import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// This repo lives on an external exFAT volume (/Volumes/T7) — the same class
// of problem documented in this org's other Next.js projects on T7 (e.g.
// ph-fuel-watch's next.config.mjs): persistent filesystem dev caches (both
// webpack's and Turbopack's) can fail their atomic rename/write against
// exFAT, or choke on the AppleDouble `._*` sidecar files macOS creates there.
// In-memory-only caching avoids both failure modes; only cost is a slightly
// slower cold start, never worth the flaky-cache debugging time.
const nextConfig: NextConfig = {
  webpack(config, { dev }) {
    if (dev) config.cache = { type: "memory" };
    return config;
  },
  experimental: {
    turbopackFileSystemCacheForDev: false,
    turbopackFileSystemCacheForBuild: false,
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              // MapLibre GL needs: 'wasm-unsafe-eval' (shader compilation),
              // blob: (spawns web workers via blob: URLs). 'unsafe-inline'
              // is also required for Next.js App Router's own inline
              // hydration scripts (__next_f) — omitting it breaks
              // hydration entirely, a known gotcha in this org's other
              // Next.js projects, not a MapLibre-specific need. 'unsafe-eval'
              // dev-only: webpack HMR uses eval(); the prod build does not
              // (hit this live: first run threw "Evaluating a string as
              // JavaScript violates CSP" from Next's dev client — missed
              // porting this one bit of ph-fuel-watch's next.config.mjs).
              `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""} 'wasm-unsafe-eval' blob:`,
              "style-src 'self' 'unsafe-inline'",
              // TODO(4-4/tiles): once R2's public serving domain for COG
              // tiles is decided (spec.md §Week4 — custom domain vs. Worker
              // proxy, still open), add it here. Left out now rather than
              // guessing a domain that might not be the one actually chosen.
              "img-src 'self' data: blob:",
              "font-src 'self'",
              // Week4-5's rainfall overlay: api.librewxr.net serves both the
              // frame-index JSON (fetched server-side in page.tsx — doesn't
              // need CSP at all) and the actual XYZ tile images MapLibre
              // requests client-side (the reason this entry exists).
              `connect-src 'self' https://tiles.openfreemap.org https://api.librewxr.net ${process.env.NEXT_PUBLIC_SUPABASE_URL ?? ""}`,
              "worker-src 'self' blob:",
              "frame-ancestors 'none'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
