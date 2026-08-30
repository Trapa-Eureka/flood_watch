import "server-only";
import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

// Week 4-9: the session-aware counterpart to supabase-public.ts's anon-only
// singleton. That module NEVER carries a visitor's own login — every call
// through it is anon-tier, full stop, which is exactly why a real logged-in
// viewer never actually reached the `authenticated` RLS tier (Week1-3's
// draft policies) despite that tier already existing at the DB level. This
// client reads the actual session cookie @supabase/ssr's middleware
// refreshes on every request (see web/middleware.ts), so RLS sees the real
// caller — anon, authenticated-viewer, or authenticated-admin — not a
// hardcoded anon key regardless of who's actually looking.
//
// One new client per request (never shared/cached across requests) per
// @supabase/ssr's own docs — a request-scoped client is the only way session
// cookies stay correctly isolated between concurrent requests from different
// users.
async function supabaseServer() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY not set in web/.env.local — see .env.local.example.",
    );
  }

  const cookieStore = await cookies();

  return createServerClient(url, key, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
        } catch {
          // Called from a Server Component (not a Route Handler or Server
          // Action) — Next.js doesn't allow setting cookies there. Harmless
          // as long as web/middleware.ts is also refreshing the session on
          // every request (it is) — this is the exact tradeoff @supabase/
          // ssr's own createServerClient docs describe.
        }
      },
    },
  });
}

export default supabaseServer;
