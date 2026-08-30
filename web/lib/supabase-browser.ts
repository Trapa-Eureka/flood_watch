"use client";

import { createBrowserClient } from "@supabase/ssr";

// Week 4-9: browser-side client for web/app/login/page.tsx's
// signInWithOtp() call — @supabase/ssr's createBrowserClient stores the
// session in cookies (not localStorage, unlike plain @supabase/supabase-js)
// so the server-side client (lib/supabase-server.ts) and middleware can
// both read the same session on the next request.
function supabaseBrowser() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY not set");
  }
  return createBrowserClient(url, key);
}

export default supabaseBrowser;
