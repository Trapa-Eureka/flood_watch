import maplibregl from "maplibre-gl";

// Shared MapLibre instance setup — extracted out of MapView.tsx (Week 4-1)
// so the AOI-drawing map (Week 4-2, app/admin/_components/AoiBboxMap.tsx)
// doesn't duplicate the same style-load-retry/resize boilerplate. Both
// components need the same base map; only what's layered on top differs.

export const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

// Whole-archipelago default view — see MapView.tsx's Week 4-1 note (this
// dashboard covers any AOI in the Philippines, not one fixed city).
export const PH_CENTER: [number, number] = [121.0, 12.8];
export const PH_ZOOM = 5.3;

/** Creates a MapLibre map on *container* with this project's standard setup
 * (OpenFreeMap style + self-healing reload + missing-sprite fix + a
 * ResizeObserver so the canvas always tracks its real container size — see
 * Week 4-1's design-notes.md for why each of these exists). Returns the map
 * instance and a cleanup function; call cleanup from the caller's effect
 * cleanup. */
export function createBaseMap(
  container: HTMLElement,
  overrides?: Partial<maplibregl.MapOptions>,
): { map: maplibregl.Map; cleanup: () => void } {
  const map = new maplibregl.Map({
    container,
    style: MAP_STYLE,
    center: PH_CENTER,
    zoom: PH_ZOOM,
    attributionControl: { compact: true },
    ...overrides,
  });

  let styleTries = 0;
  let retryTimer: ReturnType<typeof setTimeout> | undefined;
  const ensureMapStyle = () => {
    if (map.isStyleLoaded() || styleTries >= 3) return;
    styleTries++;
    try {
      map.setStyle(MAP_STYLE, { diff: false });
    } catch {
      // swallow — retried on the next timer tick regardless
    }
    retryTimer = setTimeout(ensureMapStyle, 4000);
  };
  retryTimer = setTimeout(ensureMapStyle, 5000);

  const blankPixel = { width: 1, height: 1, data: new Uint8Array(4) };
  map.on("styleimagemissing", (e) => {
    if (!map.hasImage(e.id)) map.addImage(e.id, blankPixel);
  });

  const resizeObserver = new ResizeObserver(() => map.resize());
  resizeObserver.observe(container);

  const cleanup = () => {
    clearTimeout(retryTimer);
    resizeObserver.disconnect();
    map.remove();
  };

  return { map, cleanup };
}
