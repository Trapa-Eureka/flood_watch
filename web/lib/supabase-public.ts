import { createClient } from "@supabase/supabase-js";

// The actual public-facing dashboard client — anon key, subject to RLS
// (supabase/migrations/*_rls_policies.sql). Deliberately NOT service_role:
// Week 4-3's event list/detail pages are what a real anon or authenticated
// visitor would see, so they must go through the same RLS boundary a real
// visitor hits, not bypass it — that's the only way this actually tests the
// access-control design instead of just trusting it reads right in a review.
function supabasePublic() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY not set in web/.env.local — see .env.local.example.",
    );
  }
  return createClient(url, key, { auth: { persistSession: false } });
}

export default supabasePublic;
