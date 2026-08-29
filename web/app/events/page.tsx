import Link from "next/link";
import supabasePublic from "@/lib/supabase-public";

export const dynamic = "force-dynamic"; // event list changes as the pipeline completes new ones — never cache stale
export const metadata = { title: "PH Flood Watch — Events" };

const KIND_LABELS: Record<string, string> = {
  typhoon: "Typhoon",
  monsoon: "Monsoon",
  manual: "Manual",
  backtest: "Backtest",
};

export default async function EventsPage() {
  // Anon key, RLS-bound (see lib/supabase-public.ts) — this genuinely only
  // returns status='completed' AND visibility='public' rows (events_select_public
  // policy, Week 1-3). Registered/processing/private events are invisible
  // here on purpose, the same as a real anonymous visitor would see.
  const { data: events, error } = await supabasePublic()
    .from("events")
    .select("id, name, kind, pre_event_date, post_event_date, aois(name)")
    .order("pre_event_date", { ascending: false });

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 16 }}>Events</h1>

      {error && <p style={{ color: "#b91c1c" }}>Error: {error.message}</p>}

      {events?.length === 0 && (
        <p style={{ color: "#666" }}>No completed public events to show yet.</p>
      )}

      <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        {events?.map((e) => (
          <li key={e.id}>
            <Link
              href={`/events/${e.id}`}
              style={{
                display: "block",
                padding: 16,
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                textDecoration: "none",
                color: "inherit",
              }}
            >
              <div style={{ fontWeight: 600 }}>{e.name}</div>
              <div style={{ fontSize: 13, color: "#666", marginTop: 4 }}>
                {KIND_LABELS[e.kind] ?? e.kind} · {(e.aois as unknown as { name: string } | null)?.name ?? "No AOI"} ·{" "}
                {e.pre_event_date} → {e.post_event_date ?? "Ongoing"}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
