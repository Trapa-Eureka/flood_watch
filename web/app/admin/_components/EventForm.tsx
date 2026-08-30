"use client";

import { useEffect, useState } from "react";
import AoiBboxMap from "./AoiBboxMap";
import type { Bbox } from "../../_lib/geo";

type Aoi = { id: string; name: string; kind: "river_basin" | "custom"; watch_priority: number };
type EventKind = "typhoon" | "monsoon" | "manual" | "backtest";

const EVENT_KIND_LABELS: Record<EventKind, string> = {
  typhoon: "Typhoon",
  monsoon: "Monsoon",
  manual: "Manual",
  backtest: "Backtest",
};

function bboxFieldsValid(b: (number | "")[]): b is number[] {
  return b.every((n) => typeof n === "number" && Number.isFinite(n));
}

export default function EventForm() {
  const [aois, setAois] = useState<Aoi[] | null>(null);
  const [aoiMode, setAoiMode] = useState<"existing" | "new">("new");
  const [selectedAoiId, setSelectedAoiId] = useState("");
  const [newAoiName, setNewAoiName] = useState("");
  const [bboxFields, setBboxFields] = useState<(number | "")[]>(["", "", "", ""]); // [west, south, east, north]

  const [name, setName] = useState("");
  const [kind, setKind] = useState<EventKind>("manual");
  const [preEventDate, setPreEventDate] = useState("");
  const [postEventDate, setPostEventDate] = useState("");
  const [visibility, setVisibility] = useState<"private" | "public">("private");

  const [submitting, setSubmitting] = useState(false);
  // Deliberately two separate nullable fields rather than a
  // `{ok:true, eventId}|{ok:false, error}` discriminated union: this repo's
  // tsconfig has `strict: false` (strictNullChecks off), and TS 5.9 fails to
  // narrow a boolean-literal-discriminated union (`if (!result.ok) return
  // result.error`) without strictNullChecks — same root cause fixed in
  // web/lib/require-admin.ts. Plain nullable fields sidestep that narrowing.
  const [result, setResult] = useState<{ eventId: string } | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/aois")
      .then((r) => r.json())
      .then((d) => setAois(d.aois ?? []))
      .catch(() => setAois([]));
  }, []);

  const bbox: Bbox | null = bboxFieldsValid(bboxFields)
    ? (bboxFields as [number, number, number, number])
    : null;

  function handleMapDraw(drawn: Bbox) {
    setBboxFields(drawn.map((n) => Math.round(n * 1e6) / 1e6));
  }

  function updateBboxField(i: number, raw: string) {
    const next = [...bboxFields];
    next[i] = raw === "" ? "" : Number(raw);
    setBboxFields(next);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setResult(null);
    setSubmitError(null);

    const body: Record<string, unknown> = {
      name,
      kind,
      preEventDate,
      postEventDate: postEventDate || null,
      visibility,
    };
    if (aoiMode === "existing") {
      body.aoiId = selectedAoiId;
    } else {
      body.newAoi = { name: newAoiName, bbox };
    }

    try {
      const res = await fetch("/api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setResult({ eventId: data.event.id });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit =
    name.trim() &&
    preEventDate &&
    (aoiMode === "existing" ? !!selectedAoiId : newAoiName.trim() && bbox !== null);

  return (
    <form onSubmit={handleSubmit} style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px", display: "flex", flexDirection: "column", gap: 20 }}>
      <h1 style={{ fontSize: 22, fontWeight: 600 }}>Register Event</h1>

      <section>
        <div style={{ display: "flex", gap: 16, marginBottom: 8 }}>
          <label>
            <input type="radio" checked={aoiMode === "new"} onChange={() => setAoiMode("new")} /> New AOI
          </label>
          <label>
            <input type="radio" checked={aoiMode === "existing"} onChange={() => setAoiMode("existing")} /> Existing AOI
          </label>
        </div>

        {aoiMode === "existing" ? (
          <select value={selectedAoiId} onChange={(e) => setSelectedAoiId(e.target.value)} style={{ width: "100%", padding: 8 }}>
            <option value="">— Select AOI —</option>
            {(aois ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} {a.kind === "river_basin" ? `(priority watch, priority ${a.watch_priority})` : "(custom)"}
              </option>
            ))}
          </select>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input
              placeholder="AOI name (e.g. Cagayan Valley)"
              value={newAoiName}
              onChange={(e) => setNewAoiName(e.target.value)}
              style={{ padding: 8 }}
            />
            <p style={{ fontSize: 13, color: "#666", margin: 0 }}>
              Click and drag on the map to draw a rectangle, or enter coordinates directly below.
            </p>
            <AoiBboxMap value={bbox} onChange={handleMapDraw} />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
              {(["west", "south", "east", "north"] as const).map((label, i) => (
                <label key={label} style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
                  {label}
                  <input
                    type="number"
                    step="0.0001"
                    value={bboxFields[i]}
                    onChange={(e) => updateBboxField(i, e.target.value)}
                    style={{ padding: 6 }}
                  />
                </label>
              ))}
            </div>
          </div>
        )}
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          Event name
          <input value={name} onChange={(e) => setName(e.target.value)} style={{ padding: 8 }} />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value as EventKind)} style={{ padding: 8 }}>
            {(Object.keys(EVENT_KIND_LABELS) as EventKind[]).map((k) => (
              <option key={k} value={k}>
                {EVENT_KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </label>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Pre-event date
            <input type="date" value={preEventDate} onChange={(e) => setPreEventDate(e.target.value)} style={{ padding: 8 }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Post-event date (optional)
            <input type="date" value={postEventDate} onChange={(e) => setPostEventDate(e.target.value)} style={{ padding: 8 }} />
          </label>
        </div>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          Visibility
          <select value={visibility} onChange={(e) => setVisibility(e.target.value as "private" | "public")} style={{ padding: 8 }}>
            <option value="private">Private (default — signed-in users only)</option>
            <option value="public">Public</option>
          </select>
        </label>
      </section>

      <button type="submit" disabled={!canSubmit || submitting} style={{ padding: "10px 16px", fontWeight: 600 }}>
        {submitting ? "Registering..." : "Register Event"}
      </button>

      {(result || submitError) && (
        <p style={{ color: result ? "#166534" : "#b91c1c" }}>
          {result ? `Registered — event id: ${result.eventId}` : `Error: ${submitError}`}
        </p>
      )}
    </form>
  );
}
