"use client";

import { useEffect, useState } from "react";
import AoiBboxMap from "./AoiBboxMap";
import type { Bbox } from "../../_lib/geo";

type Aoi = { id: string; name: string; kind: "river_basin" | "custom"; watch_priority: number };
type EventKind = "typhoon" | "monsoon" | "manual" | "backtest";

const EVENT_KIND_LABELS: Record<EventKind, string> = {
  typhoon: "태풍",
  monsoon: "몬순",
  manual: "수동",
  backtest: "백테스트",
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
  const [result, setResult] = useState<{ ok: true; eventId: string } | { ok: false; error: string } | null>(null);

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
      setResult({ ok: true, eventId: data.event.id });
    } catch (err) {
      setResult({ ok: false, error: err instanceof Error ? err.message : String(err) });
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
      <h1 style={{ fontSize: 22, fontWeight: 600 }}>이벤트 등록</h1>

      <section>
        <div style={{ display: "flex", gap: 16, marginBottom: 8 }}>
          <label>
            <input type="radio" checked={aoiMode === "new"} onChange={() => setAoiMode("new")} /> 새 AOI 지정
          </label>
          <label>
            <input type="radio" checked={aoiMode === "existing"} onChange={() => setAoiMode("existing")} /> 기존 AOI 사용
          </label>
        </div>

        {aoiMode === "existing" ? (
          <select value={selectedAoiId} onChange={(e) => setSelectedAoiId(e.target.value)} style={{ width: "100%", padding: 8 }}>
            <option value="">— AOI 선택 —</option>
            {(aois ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} {a.kind === "river_basin" ? `(우선감시, priority ${a.watch_priority})` : "(custom)"}
              </option>
            ))}
          </select>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input
              placeholder="AOI 이름 (예: Cagayan Valley)"
              value={newAoiName}
              onChange={(e) => setNewAoiName(e.target.value)}
              style={{ padding: 8 }}
            />
            <p style={{ fontSize: 13, color: "#666", margin: 0 }}>
              지도 위에서 클릭·드래그로 사각형을 그리거나, 아래 좌표를 직접 입력하세요.
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
          이벤트 이름
          <input value={name} onChange={(e) => setName(e.target.value)} style={{ padding: 8 }} />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          종류
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
            사전(pre-event) 날짜
            <input type="date" value={preEventDate} onChange={(e) => setPreEventDate(e.target.value)} style={{ padding: 8 }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            사후(post-event) 날짜 (선택)
            <input type="date" value={postEventDate} onChange={(e) => setPostEventDate(e.target.value)} style={{ padding: 8 }} />
          </label>
        </div>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          공개 범위
          <select value={visibility} onChange={(e) => setVisibility(e.target.value as "private" | "public")} style={{ padding: 8 }}>
            <option value="private">비공개 (기본값 — 로그인 사용자만)</option>
            <option value="public">공개</option>
          </select>
        </label>
      </section>

      <button type="submit" disabled={!canSubmit || submitting} style={{ padding: "10px 16px", fontWeight: 600 }}>
        {submitting ? "등록 중..." : "이벤트 등록"}
      </button>

      {result && (
        <p style={{ color: result.ok ? "#166534" : "#b91c1c" }}>
          {result.ok ? `등록 완료 — event id: ${result.eventId}` : `오류: ${result.error}`}
        </p>
      )}
    </form>
  );
}
