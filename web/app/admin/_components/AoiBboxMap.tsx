"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { createBaseMap } from "../../_lib/maplibre-base";
import type { Bbox } from "../../_lib/geo";

const SOURCE_ID = "aoi-bbox";
const FILL_LAYER_ID = "aoi-bbox-fill";
const LINE_LAYER_ID = "aoi-bbox-line";
const MIN_DRAG_DEGREES = 0.0005; // ~55m — below this, treat mouseup as a stray click, not a drawn rectangle

function bboxToFeature(bbox: Bbox) {
  const [west, south, east, north] = bbox;
  return {
    type: "Feature" as const,
    properties: {},
    geometry: {
      type: "Polygon" as const,
      coordinates: [
        [
          [west, south],
          [east, south],
          [east, north],
          [west, north],
          [west, south],
        ],
      ],
    },
  };
}

function toFeatureCollection(bbox: Bbox | null) {
  return { type: "FeatureCollection" as const, features: bbox ? [bboxToFeature(bbox)] : [] };
}

/** Click-drag rectangle drawing — not a general polygon tool, because the
 * whole backend pipeline (pipeline/config.py's AOI_BBOX and everything
 * downstream: baseline_diff, population.crop_to_bbox, buildings' bbox
 * queries) only ever works with an axis-aligned bbox, never an arbitrary
 * hand-drawn shape. A full drawing library (e.g. mapbox-gl-draw) would let
 * users draw shapes the rest of this project can't actually use — a plain
 * rectangle tool is a better match for what AOIs really are here, not a
 * shortcut taken to save time. */
export default function AoiBboxMap({ value, onChange }: { value: Bbox | null; onChange: (bbox: Bbox) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const drawStartRef = useRef<[number, number] | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const { map, cleanup } = createBaseMap(containerRef.current);
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      map.addSource(SOURCE_ID, { type: "geojson", data: toFeatureCollection(valueRef.current) });
      map.addLayer({ id: FILL_LAYER_ID, type: "fill", source: SOURCE_ID, paint: { "fill-color": "#2563eb", "fill-opacity": 0.15 } });
      map.addLayer({ id: LINE_LAYER_ID, type: "line", source: SOURCE_ID, paint: { "line-color": "#2563eb", "line-width": 2 } });
    });

    const setRect = (bbox: Bbox | null) => {
      const source = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
      source?.setData(toFeatureCollection(bbox));
    };
    const bboxFrom = (start: [number, number], end: maplibregl.LngLat): Bbox => [
      Math.min(start[0], end.lng),
      Math.min(start[1], end.lat),
      Math.max(start[0], end.lng),
      Math.max(start[1], end.lat),
    ];

    const onMouseDown = (e: maplibregl.MapMouseEvent) => {
      drawStartRef.current = [e.lngLat.lng, e.lngLat.lat];
      map.dragPan.disable();
      map.getCanvas().style.cursor = "crosshair";
    };
    const onMouseMove = (e: maplibregl.MapMouseEvent) => {
      if (!drawStartRef.current) return;
      setRect(bboxFrom(drawStartRef.current, e.lngLat));
    };
    const onMouseUp = (e: maplibregl.MapMouseEvent) => {
      const start = drawStartRef.current;
      if (!start) return;
      drawStartRef.current = null;
      map.dragPan.enable();
      map.getCanvas().style.cursor = "";
      const bbox = bboxFrom(start, e.lngLat);
      if (bbox[2] - bbox[0] > MIN_DRAG_DEGREES && bbox[3] - bbox[1] > MIN_DRAG_DEGREES) {
        onChange(bbox);
      } else {
        setRect(valueRef.current); // stray click, not a drag — restore whatever was there
      }
    };

    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("mouseup", onMouseUp);

    return () => {
      map.off("mousedown", onMouseDown);
      map.off("mousemove", onMouseMove);
      map.off("mouseup", onMouseUp);
      cleanup();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally init-once; value changes are synced by the effect below, not by re-running this one
  }, []);

  // keep the drawn rectangle in sync when `value` changes from outside this
  // component (the manual bbox number inputs in EventForm.tsx)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const source = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
      source?.setData(toFeatureCollection(value));
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [value]);

  return (
    <div
      ref={containerRef}
      style={{ position: "relative", width: "100%", height: "420px", borderRadius: 8, overflow: "hidden" }}
    />
  );
}
