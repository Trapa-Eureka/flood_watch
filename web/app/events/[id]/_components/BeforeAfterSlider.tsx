"use client";

import { useCallback, useRef, useState } from "react";

/** Classic drag-to-reveal comparison slider. Handles the real, spec-anticipated
 * case where there's no "before" image at all (Week 1-5/1-8: a baseline
 * scene can genuinely fail the AOI-local cloud-cover bar, e.g. the Marikina
 * Kristine/Trami event) by falling back to a plain single image with an
 * honest note, instead of a broken/half-rendered slider. */
export default function BeforeAfterSlider({
  beforeSrc,
  afterSrc,
  beforeLabel = "사전(pre-event)",
  afterLabel = "사후(post-event)",
}: {
  beforeSrc: string | null;
  afterSrc: string;
  beforeLabel?: string;
  afterLabel?: string;
}) {
  const [pct, setPct] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  const updateFromClientX = useCallback((clientX: number) => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const next = ((clientX - rect.left) / rect.width) * 100;
    setPct(Math.min(100, Math.max(0, next)));
  }, []);

  if (!beforeSrc) {
    return (
      <div>
        <img src={afterSrc} alt={afterLabel} style={{ width: "100%", borderRadius: 8, display: "block" }} />
        <p style={{ fontSize: 13, color: "#666", marginTop: 8 }}>
          이 이벤트는 사전(pre-event) 이미지가 없습니다 — 태풍 직후 구름으로 AOI 국소 품질 기준을 통과하는 사전
          촬영본을 확보하지 못했습니다(실제 데이터 한계, 표시 오류 아님).
        </p>
      </div>
    );
  }

  return (
    <div>
      <div
        ref={containerRef}
        onMouseDown={(e) => {
          draggingRef.current = true;
          updateFromClientX(e.clientX);
        }}
        onMouseMove={(e) => draggingRef.current && updateFromClientX(e.clientX)}
        onMouseUp={() => (draggingRef.current = false)}
        onMouseLeave={() => (draggingRef.current = false)}
        onTouchStart={(e) => updateFromClientX(e.touches[0].clientX)}
        onTouchMove={(e) => updateFromClientX(e.touches[0].clientX)}
        style={{
          position: "relative",
          width: "100%",
          aspectRatio: "4 / 3",
          borderRadius: 8,
          overflow: "hidden",
          cursor: "ew-resize",
          userSelect: "none",
        }}
      >
        <img
          src={afterSrc}
          alt={afterLabel}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
          draggable={false}
        />
        <div style={{ position: "absolute", inset: 0, width: `${pct}%`, overflow: "hidden" }}>
          <img
            src={beforeSrc}
            alt={beforeLabel}
            style={{ width: containerRef.current?.clientWidth ?? "100%", height: "100%", objectFit: "cover", maxWidth: "none" }}
            draggable={false}
          />
        </div>
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: `${pct}%`,
            width: 2,
            background: "#fff",
            boxShadow: "0 0 4px rgba(0,0,0,0.5)",
            transform: "translateX(-1px)",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: `${pct}%`,
            transform: "translate(-50%, -50%)",
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "#fff",
            boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 12,
          }}
        >
          ⇔
        </div>
        <span style={{ position: "absolute", top: 8, left: 8, background: "rgba(0,0,0,0.55)", color: "#fff", fontSize: 11, padding: "2px 6px", borderRadius: 4 }}>
          {beforeLabel}
        </span>
        <span style={{ position: "absolute", top: 8, right: 8, background: "rgba(0,0,0,0.55)", color: "#fff", fontSize: 11, padding: "2px 6px", borderRadius: 4 }}>
          {afterLabel}
        </span>
      </div>
      <p style={{ fontSize: 12, color: "#999", marginTop: 6 }}>드래그해서 사전/사후 비교</p>
    </div>
  );
}
