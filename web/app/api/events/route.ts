import { NextResponse } from "next/server";
import supabaseAdmin from "@/lib/supabase-admin";
import { bboxToWktPolygon, isValidBbox, type Bbox } from "@/app/_lib/geo";

const EVENT_KINDS = ["typhoon", "monsoon", "manual", "backtest"] as const;
type EventKind = (typeof EVENT_KINDS)[number];

type CreateEventBody = {
  aoiId?: string;
  newAoi?: { name: string; bbox: Bbox };
  name: string;
  kind: EventKind;
  preEventDate: string;
  postEventDate?: string | null;
  visibility?: "public" | "private";
};

// POST /api/events — spec.md §7 events.create: register an event against
// either an existing AOI (aoiId) or a freshly-drawn one (newAoi), Week 4-2's
// "AOI 자유 지정 + 이벤트 등록". Runs with service_role (via supabase-admin,
// see that module's own doc comment for the Week 4-9 auth gap this
// deliberately doesn't solve yet) since aois/events have no anon/authenticated
// INSERT policy — spec.md §4 gives write access to admin only, and until
// real login exists, this route *is* that boundary, imperfect as it is.
export async function POST(req: Request) {
  let body: CreateEventBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const { aoiId, newAoi, name, kind, preEventDate, postEventDate, visibility } = body;

  if (!name?.trim()) return NextResponse.json({ error: "name is required" }, { status: 400 });
  if (!EVENT_KINDS.includes(kind)) {
    return NextResponse.json({ error: `kind must be one of ${EVENT_KINDS.join(", ")}` }, { status: 400 });
  }
  if (!preEventDate) return NextResponse.json({ error: "preEventDate is required" }, { status: 400 });
  if (postEventDate && postEventDate < preEventDate) {
    return NextResponse.json({ error: "postEventDate must not be before preEventDate" }, { status: 400 });
  }
  if (!aoiId && !newAoi) {
    return NextResponse.json({ error: "either aoiId or newAoi is required" }, { status: 400 });
  }
  if (aoiId && newAoi) {
    return NextResponse.json({ error: "pass either aoiId or newAoi, not both" }, { status: 400 });
  }
  if (newAoi && (!newAoi.name?.trim() || !isValidBbox(newAoi.bbox))) {
    return NextResponse.json({ error: "newAoi.name and a valid [west,south,east,north] bbox are required" }, { status: 400 });
  }

  const supabase = supabaseAdmin();

  let resolvedAoiId = aoiId;
  if (newAoi) {
    // 'custom' — matches the aois.kind CHECK constraint's own comment:
    // "free-form AOI drawn/entered at event-registration time". Not
    // idempotent-by-name like pipeline/repository.py's get_or_create_aoi
    // (that helper is for the pipeline's own re-run safety on a handful of
    // named priority basins) — every AOI drawn here is a genuinely new,
    // one-off shape, so a fresh row each time is correct, not a duplication bug.
    const { data: aoiRow, error: aoiError } = await supabase
      .from("aois")
      .insert({ name: newAoi.name, kind: "custom", geom: bboxToWktPolygon(newAoi.bbox), watch_priority: 0 })
      .select()
      .single();
    if (aoiError) return NextResponse.json({ error: `aois insert failed: ${aoiError.message}` }, { status: 500 });
    resolvedAoiId = aoiRow.id;
  }

  const { data: eventRow, error: eventError } = await supabase
    .from("events")
    .insert({
      aoi_id: resolvedAoiId,
      name,
      kind,
      pre_event_date: preEventDate,
      post_event_date: postEventDate || null,
      visibility: visibility ?? "private",
    })
    .select()
    .single();
  if (eventError) return NextResponse.json({ error: `events insert failed: ${eventError.message}` }, { status: 500 });

  return NextResponse.json({ event: eventRow }, { status: 201 });
}

// GET /api/events — Week4-6 admin event list (every status, not just
// completed+public like the RLS-scoped public /events page) — service_role,
// same reasoning as GET /api/aois: admins need to see 'registered'/
// 'processing'/'failed' rows to actually trigger/monitor the pipeline.
export async function GET() {
  const { data, error } = await supabaseAdmin()
    .from("events")
    .select("id, name, kind, status, visibility, pre_event_date, post_event_date, created_at, aois(name)")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ events: data });
}
