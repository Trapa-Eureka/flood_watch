// WGS84 [west, south, east, north] — same convention as pipeline/config.py's
// AOI_BBOX / MARIKINA_CITY_BBOX throughout the Python pipeline.
export type Bbox = [number, number, number, number];

/** Mirrors pipeline/repository.py's _bbox_to_wkt_polygon exactly (same
 * closed-ring WKT shape) — the Python pipeline and this web app are peer
 * PostgREST clients of the same DB, not one calling the other, so both need
 * their own copy of this, kept in sync by convention. */
export function bboxToWktPolygon([west, south, east, north]: Bbox): string {
  return `POLYGON((${west} ${south}, ${east} ${south}, ${east} ${north}, ${west} ${north}, ${west} ${south}))`;
}

export function isValidBbox(b: unknown): b is Bbox {
  if (!Array.isArray(b) || b.length !== 4) return false;
  const [west, south, east, north] = b;
  if (![west, south, east, north].every((n) => typeof n === "number" && Number.isFinite(n))) return false;
  if (west >= east || south >= north) return false;
  if (west < -180 || east > 180 || south < -90 || north > 90) return false;
  return true;
}
