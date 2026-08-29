import "server-only";
import { createClient } from "@supabase/supabase-js";

// service_role bypasses RLS entirely (supabase/migrations/*_rls_policies.sql's
// own comment: "admin is simply the service_role key the pipeline backend
// holds"). The `server-only` import above makes any accidental client-side
// import of this module a build-time error, not just a lint warning — this
// key must never reach the browser bundle.
//
// Known, deliberate gap (same migration's own comment): there is no real
// human-admin login yet, so any Route Handler that imports this module is
// currently reachable by anyone who can hit the deployed URL, not just an
// authenticated admin. Week 4-9 ("인증/역할 적용", renumbered from 4-8 by the
// 2026-08-29 home dashboard redesign) is where that gets closed — not fixed
// here, and not silently ignored either.
function supabaseAdmin() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set in web/.env.local — see .env.local.example.",
    );
  }
  return createClient(url, key, { auth: { persistSession: false } });
}

export default supabaseAdmin;
