import "server-only";
import { NextResponse } from "next/server";
import supabaseServer from "@/lib/supabase-server";

// Week 4-9: the Route Handler counterpart to web/middleware.ts's page-level
// /admin gate — every route under /api/events* that uses supabase-admin.ts
// (service_role, bypasses RLS) calls this FIRST and returns its response
// immediately if not ok. Middleware alone doesn't cover this: it only
// redirects browser navigations to /admin, not JSON API calls, and (per
// web/middleware.ts's own comment) a single path's GET vs POST can have
// different authorization needs in ways the middleware matcher can't
// express cleanly.
//
// Returns null when the caller may proceed, or a NextResponse to return
// immediately otherwise — deliberately NOT a `{ok:true}|{ok:false,response}`
// discriminated union: this repo's tsconfig has `strict: false`
// (strictNullChecks off), and found live that TS 5.9 fails to narrow a
// boolean-literal-discriminated union (`if (!x.ok) return x.response`)
// without strictNullChecks — `x.response` doesn't type-check even on the
// `ok:false` branch. A plain nullable return sidesteps that narrowing
// entirely rather than flipping a project-wide strict flag for one helper.
export async function requireAdmin(): Promise<NextResponse | null> {
  const supabase = await supabaseServer();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "not signed in" }, { status: 401 });
  }

  const { data: isAdmin, error } = await supabase.rpc("is_admin");
  if (error) {
    return NextResponse.json({ error: `role check failed: ${error.message}` }, { status: 500 });
  }
  if (!isAdmin) {
    return NextResponse.json({ error: "admin role required" }, { status: 403 });
  }

  return null;
}
