import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

// Week 4-9: two jobs, both required by @supabase/ssr's own docs —
//
// 1. Refresh the session cookie on every request (calling getUser() below
//    does this side-effect: it revalidates the JWT and, if expired, uses
//    the refresh token to mint a new one and writes it back via setAll).
//    Skipping this is the #1 cause of "random logouts" the library's own
//    createServerClient docs warn about — Server Components can't
//    reliably write cookies themselves (see supabase-server.ts's setAll
//    try/catch), so this middleware is the one place guaranteed to run on
//    every request and able to persist a refreshed token.
// 2. Gate /admin/* — the actual authorization boundary Week 4-9 exists to
//    close (web/lib/supabase-admin.ts's own comment has been flagging this
//    gap since Week 4-2: "any Route Handler that imports this module is
//    currently reachable by anyone who can hit the deployed URL").
//    /api/events* (the routes that actually use supabase-admin.ts) are
//    gated in each route individually, not here — a redirect response
//    doesn't make sense for a JSON API, and Next.js middleware matchers
//    can't easily express "this GET is public, this POST on the same path
//    isn't" (GET /api/events/[id]/report is intentionally public-ish,
//    RLS-gated; POST /api/events/[id]/run is admin-only) as cleanly as a
//    per-route check does.
export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
        },
      },
    },
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (request.nextUrl.pathname.startsWith("/admin")) {
    if (!user) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("next", request.nextUrl.pathname);
      return NextResponse.redirect(loginUrl);
    }

    const { data: isAdmin } = await supabase.rpc("is_admin");
    if (!isAdmin) {
      const forbiddenUrl = new URL("/login", request.url);
      forbiddenUrl.searchParams.set("error", "not_admin");
      return NextResponse.redirect(forbiddenUrl);
    }
  }

  return response;
}

export const config = {
  matcher: [
    // Every path except static assets and Next's own internals — the
    // getUser() refresh above should run broadly (any page can carry a
    // session), but skip anything that's obviously not app content.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
