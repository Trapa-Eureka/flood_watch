import { NextResponse } from "next/server";
import supabaseAdmin from "@/lib/supabase-admin";

// GET /api/aois — list existing AOIs (for the admin form's "reuse an
// existing AOI" dropdown, Week 4-2). Read-only, but still goes through
// service_role (not the anon key) so it's consistent with how the write
// side works — RLS's aois_select_all policy would let anon read this too,
// but there's no reason to hold two different Supabase clients for one page.
export async function GET() {
  const { data, error } = await supabaseAdmin()
    .from("aois")
    .select("id, name, kind, watch_priority")
    .order("watch_priority", { ascending: false })
    .order("name");

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ aois: data });
}
