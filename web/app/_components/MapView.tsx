"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { createBaseMap } from "../_lib/maplibre-base";

export default function MapView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const { map, cleanup } = createBaseMap(containerRef.current);
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

    return () => {
      cleanup();
      mapRef.current = null;
    };
  }, []);

  return <div id="map" ref={containerRef} />;
}
