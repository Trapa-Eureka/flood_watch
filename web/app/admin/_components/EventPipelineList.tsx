"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type EventRow = {
  id: string;
  name: string;
  kind: string;
  status: "registered" | "processing" | "completed" | "failed";
  visibility: "public" | "private";
  pre_event_date: string;
  post_event_date: string | null;
  created_at: string;
  aois: { name: string } | null;
};

type StepRow = { step: string; status: "success" | "failed"; created_at: string; output: unknown };

const STATUS_COLOR: Record<EventRow["status"], string> = {
  registered: "#6b7280",
  processing: "#2563eb",
  completed: "#166534",
  failed: "#b91c1c",
};

const STEP_LABEL: Record<string, string> = {
  "scenes.fetch": "Fetch scenes",
  "preprocess.run": "Preprocess",
  "inference.run": "Run inference",
  "baseline.diff": "Baseline diff",
  "vectorize.extract": "Vectorize",
  "exposure.compute": "Compute exposure",
  "tiles.publish": "Publish tiles",
};

const POLL_INTERVAL_MS = 4000;

/** Week4-6 admin trigger UI: lists every registered event (any status, not
 * just completed+public — this is the admin's own view of pipeline state)
 * with a "Run Pipeline" button and live step-by-step progress polling. The
 * button POSTs /api/events/{id}/run (spawns pipeline/orchestrator.py in the
 * background) and this component then polls /api/events/{id}/status every
 * few seconds — real pipeline_events audit-log rows, not a simulated
 * progress bar — until the event reaches 'completed' or 'failed'. */
export default function EventPipelineList() {
  const [events, setEvents] = useState<EventRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<Record<string, StepRow[]>>({});
  const [triggering, setTriggering] = useState<Record<string, boolean>>({});
  const [runError, setRunError] = useState<Record<string, string>>({});
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  const loadEvents = useCallback(async () => {
    try {
      const res = await fetch("/api/events");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setEvents(data.events ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  const pollStatus = useCallback(
    (id: string) => {
      const tick = async () => {
        try {
          const res = await fetch(`/api/events/${id}/status`);
          if (!res.ok) return;
          const data = await res.json();
          setSteps((prev) => ({ ...prev, [id]: data.steps ?? [] }));
          setEvents((prev) => (prev ?? []).map((e) => (e.id === id ? { ...e, status: data.event.status } : e)));
          if (data.event.status === "completed" || data.event.status === "failed") {
            clearInterval(pollTimers.current[id]);
            delete pollTimers.current[id];
          }
        } catch {
          // transient fetch error — the interval just tries again next tick
        }
      };
      if (pollTimers.current[id]) clearInterval(pollTimers.current[id]);
      pollTimers.current[id] = setInterval(tick, POLL_INTERVAL_MS);
      tick();
    },
    [],
  );

  useEffect(() => {
    // Resume polling on load for any event already mid-run (e.g. page was
    // refreshed while the pipeline was still going) — otherwise a
    // 'processing' row would just sit there with no live updates.
    (events ?? []).filter((e) => e.status === "processing").forEach((e) => pollStatus(e.id));
    return () => {
      Object.values(pollTimers.current).forEach(clearInterval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events === null]);

  async function handleRun(id: string) {
    setTriggering((prev) => ({ ...prev, [id]: true }));
    setRunError((prev) => ({ ...prev, [id]: "" }));
    try {
      const res = await fetch(`/api/events/${id}/run`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setEvents((prev) => (prev ?? []).map((e) => (e.id === id ? { ...e, status: "processing" } : e)));
      pollStatus(id);
    } catch (err) {
      setRunError((prev) => ({ ...prev, [id]: err instanceof Error ? err.message : String(err) }));
    } finally {
      setTriggering((prev) => ({ ...prev, [id]: false }));
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 16 }}>Events</h1>

      {error && <p style={{ color: "#b91c1c" }}>Error: {error}</p>}
      {events?.length === 0 && <p style={{ color: "#666" }}>No events registered yet.</p>}

      <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
        {events?.map((e) => (
          <li key={e.id} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div>
                <div style={{ fontWeight: 600 }}>{e.name}</div>
                <div style={{ fontSize: 12, color: "#666", marginTop: 2 }}>
                  {e.kind} · {e.aois?.name ?? "No AOI"} · {e.pre_event_date} → {e.post_event_date ?? "ongoing"} ·{" "}
                  {e.visibility}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.03em",
                    color: STATUS_COLOR[e.status],
                  }}
                >
                  {e.status}
                </span>
                {(e.status === "registered" || e.status === "failed") && (
                  <button
                    onClick={() => handleRun(e.id)}
                    disabled={!!triggering[e.id]}
                    style={{ padding: "6px 12px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                  >
                    {triggering[e.id] ? "Starting..." : e.status === "failed" ? "Retry pipeline" : "Run pipeline"}
                  </button>
                )}
              </div>
            </div>

            {runError[e.id] && <p style={{ color: "#b91c1c", fontSize: 12, marginTop: 8 }}>{runError[e.id]}</p>}

            {(e.status === "processing" || (steps[e.id]?.length ?? 0) > 0) && (
              <ol style={{ listStyle: "none", padding: 0, marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
                {(steps[e.id] ?? []).map((s, i) => (
                  <li key={i} style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ color: s.status === "success" ? "#166534" : "#b91c1c" }}>
                      {s.status === "success" ? "✓" : "✗"}
                    </span>
                    <span style={{ color: "#333" }}>{STEP_LABEL[s.step] ?? s.step}</span>
                  </li>
                ))}
                {e.status === "processing" && (
                  <li style={{ fontSize: 12, color: "#999" }}>… running</li>
                )}
              </ol>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
