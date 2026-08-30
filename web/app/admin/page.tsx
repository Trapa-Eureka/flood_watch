import { redirect } from "next/navigation";
import supabaseServer from "@/lib/supabase-server";
import EventForm from "./_components/EventForm";
import EventPipelineList from "./_components/EventPipelineList";

export const metadata = { title: "PH Flood Watch — Admin" };
export const dynamic = "force-dynamic";

export default async function AdminPage() {
  // Week 4-9: web/middleware.ts already redirects a non-admin away from
  // /admin before this Server Component even runs — this is defense in
  // depth, not the primary check (same "belt and suspenders" pattern
  // web/lib/require-admin.ts uses for the API routes). Re-checking here
  // means this page is still correct even if middleware.ts's matcher ever
  // gets edited to stop covering /admin by accident.
  const supabase = await supabaseServer();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/admin");

  const { data: isAdmin } = await supabase.rpc("is_admin");
  if (!isAdmin) redirect("/login?error=not_admin");

  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", padding: "12px 16px 0" }}>
        <span style={{ fontSize: 13, color: "#666", marginRight: 12 }}>{user.email}</span>
        <form action="/auth/signout" method="POST">
          <button
            type="submit"
            style={{ fontSize: 13, color: "#666", background: "none", border: "1px solid #d1d5db", borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}
          >
            Sign out
          </button>
        </form>
      </div>
      <EventForm />
      <EventPipelineList />
    </>
  );
}
