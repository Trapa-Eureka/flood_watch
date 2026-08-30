import { NextResponse } from "next/server";
import supabaseServer from "@/lib/supabase-server";

// POST /auth/signout — clears the session cookie. POST (not GET) so this
// can't be triggered by a stray link prefetch or crawler.
export async function POST(request: Request) {
  const supabase = await supabaseServer();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/", request.url));
}
