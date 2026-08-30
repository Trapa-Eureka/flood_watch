# stale-event-watchdog

Cloudflare Worker + Cron Trigger (Week 4-8). See `src/index.ts`'s module
docstring for what this does and why — short version: every 5 minutes it
sweeps for `events` rows stuck at `status='processing'` for over 20 minutes
(a genuinely dead/orphaned background pipeline run, per `web/app/api/events/
[id]/run/route.ts`'s own staleness convention) and marks them `failed`, with
an audit-log row in `pipeline_events`.

## Setup (one-time, already done for this project — kept here for reference)

```bash
npm install
npx wrangler deploy
printf '%s' "$SUPABASE_SERVICE_ROLE_KEY" | npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
```

`SUPABASE_URL` and `STALE_MINUTES` are plain (non-secret) vars in
`wrangler.toml`. `SUPABASE_SERVICE_ROLE_KEY` must be set as an encrypted
secret (above) — it's needed because `processing`/`failed` events are
invisible to the anon key under this project's RLS policies.

## Local dev / testing

Local `wrangler dev` does NOT pull the remote secret — create a
`.dev.vars` file (gitignored) with:

```
SUPABASE_SERVICE_ROLE_KEY=<the same value as .env's SUPABASE_SERVICE_ROLE_KEY at the repo root>
```

Then:

```bash
npx wrangler dev --test-scheduled
curl "http://localhost:8787/__scheduled?cron=*/5+*+*+*+*"
```

To test against a real event without waiting 20 real minutes, override the
threshold for that one dev session only:

```bash
npx wrangler dev --var STALE_MINUTES:0 --test-scheduled
```

**Careful with this against the real project's Supabase** (there's no
separate staging DB) — a `0`-minute threshold will sweep up ANY currently-
`processing` event, including a real pipeline run someone else has genuinely
in flight, not just a dedicated test row. This actually happened once during
Week 4-8's own development (see `docs/design-notes.md`, "Week 4-8" — a real
in-progress event2 re-run got marked `failed` mid-flight by exactly this).
It self-corrected once that run's orchestrator process reached its own
`update_event_status(..., "completed")` call, but it's a real footgun to
avoid repeating: create a dedicated test event and set its `status` to
`processing` yourself, and confirm nothing else is `processing` in the
target project first.

## Redeploy after editing `src/index.ts`

```bash
npx tsc --noEmit   # typecheck first
npx wrangler deploy
```

Secrets and cron schedule persist across `deploy` — only rerun `secret put`
if the key value itself changes.
