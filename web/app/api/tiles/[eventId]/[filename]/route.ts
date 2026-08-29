import { NextResponse } from "next/server";
import { readFile, stat } from "fs/promises";
import path from "path";

// GET /api/tiles/{eventId}/{filename} — serves the local preview/COG files
// pipeline/tiles.py's publish_event_tiles() writes to
// data/output/tiles/{event_id}/*. A LOCAL-DEV BRIDGE, not the real production
// path: R2 credentials aren't set yet (Week 1-4's still-open gap), so there's
// no public CDN URL to point <img>/COG readers at. Once R2 is configured
// (Week 4-7 territory, or whenever that gap finally closes), this route goes
// away and the frontend reads scene_refs.cog_storage_key / an R2 public URL
// directly instead — this only works because the Next server and the Python
// pipeline's data/output/ happen to sit on the same machine right now, which
// won't be true once this is actually deployed (e.g. to Vercel).
const TILES_ROOT = path.resolve(process.cwd(), "..", "data", "output", "tiles");

const CONTENT_TYPES: Record<string, string> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".tif": "image/tiff",
  ".tiff": "image/tiff",
};

export async function GET(_req: Request, { params }: { params: Promise<{ eventId: string; filename: string }> }) {
  const { eventId, filename } = await params;

  // path-traversal guard: reject anything that isn't a bare id/filename
  // component (no slashes, no "..") — this route takes untrusted input
  // straight from the URL.
  if (!/^[\w-]+$/.test(eventId) || !/^[\w.-]+$/.test(filename) || filename.includes("..")) {
    return NextResponse.json({ error: "invalid path" }, { status: 400 });
  }

  const filePath = path.join(TILES_ROOT, eventId, filename);
  if (!filePath.startsWith(TILES_ROOT)) {
    return NextResponse.json({ error: "invalid path" }, { status: 400 });
  }

  try {
    await stat(filePath);
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  const data = await readFile(filePath);
  const ext = path.extname(filename).toLowerCase();
  return new NextResponse(new Uint8Array(data), {
    headers: {
      "Content-Type": CONTENT_TYPES[ext] ?? "application/octet-stream",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
