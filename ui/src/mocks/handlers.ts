/**
 * mocks/handlers.ts
 * ==================
 * Mock Service Worker (MSW) request handlers — a stand-in backend that
 * implements every endpoint in DESIGN.md Section 6, using the fixtures in
 * mocks/fixtures/. This is what lets the whole UI run and demo correctly
 * with zero real backend running.
 *
 * IMPORTANT for whoever wires up the real orchestrator: this file is the
 * one place that should stop being imported once `api/client.ts` points at
 * a real server (see main.tsx). Nothing else in `src/` imports from
 * `mocks/` — components and stores only ever import from `api/client.ts`
 * and `api/types.ts`.
 */
import { http, HttpResponse } from "msw";
import { booleanPointInPolygon, point as turfPoint } from "@turf/turf";

import type {
  ApiErrorBody,
  ChatMessage,
  QueryRequest,
  SegmentRequest,
  SegmentResponse,
  UploadResponse,
} from "../api/types";
import { newLocalId } from "../lib/id";
import { MOCK_PATCH_COLLECTION, mockTimeseriesFor } from "./fixtures/patches";
import { appendTurn, createSession, getSession, listSessions } from "./fixtures/sessions";
import { buildMockQueryResponse } from "./mockQuery";
import { placeholderPreview, placeholderSvgString } from "./placeholderImage";

/** Small helper so every handler returns errors in the exact §6.9 shape. */
function apiError(status: number, body: ApiErrorBody) {
  return HttpResponse.json(body, { status });
}

const ALLOWED_UPLOAD_EXTENSIONS = ["tif", "tiff", "png", "jpg", "jpeg"] as const;

export const handlers = [
  // -------------------------------------------------------------------
  // POST /api/query — the orchestrator's main entry point (§6.2)
  // -------------------------------------------------------------------
  http.post("/api/query", async ({ request }) => {
    const body = (await request.json()) as QueryRequest;
    const answer = buildMockQueryResponse(body.query, body.contextSet);

    const now = new Date().toISOString();
    const userMessage: ChatMessage = {
      id: newLocalId("msg"),
      role: "user",
      text: body.query,
      contextSetId: body.contextSet.id,
      createdAt: now,
    };
    const assistantMessage: ChatMessage = {
      id: newLocalId("msg"),
      role: "assistant",
      text: answer.answer,
      groundedSpans: answer.groundedSpans,
      evidence: answer.evidence,
      confidence: answer.confidence,
      executionTrace: answer.executionTrace,
      reportUrl: answer.reportUrl,
      contextSetId: body.contextSet.id,
      createdAt: new Date().toISOString(),
    };
    appendTurn(body.sessionId, body.contextSet, userMessage, assistantMessage);

    return HttpResponse.json(answer);
  }),

  // -------------------------------------------------------------------
  // POST /api/segment — point-segment tool (§6.3)
  // -------------------------------------------------------------------
  http.post("/api/segment", async ({ request }) => {
    const body = (await request.json()) as SegmentRequest;
    const { lat, lon } = body.point;

    // Which mock patches does this point fall inside? A real segmentation
    // model would derive this from the actual mask footprint; the mock
    // approximates it with a point-in-polygon test against our fixture
    // footprints so the UI still gets a believable resolvedPatchIds list.
    const clicked = turfPoint([lon, lat]);
    const resolvedPatchIds = MOCK_PATCH_COLLECTION.features
      .filter((f) => booleanPointInPolygon(clicked, f))
      .map((f) => f.properties.patchId);

    // A small square "mask" around the clicked point, just so there's a
    // real geometry to draw as a pending selection.
    const d = 0.002;
    const geometry: GeoJSON.Polygon = {
      type: "Polygon",
      coordinates: [
        [
          [lon - d, lat - d],
          [lon + d, lat - d],
          [lon + d, lat + d],
          [lon - d, lat + d],
          [lon - d, lat - d],
        ],
      ],
    };

    const response: SegmentResponse = {
      geometry,
      resolvedPatchIds: resolvedPatchIds.length > 0 ? resolvedPatchIds : [body.patchIdHint ?? "unknown"],
      confidence: 0.87,
      modelUsed: "SAM",
    };
    return HttpResponse.json(response);
  }),

  // -------------------------------------------------------------------
  // POST /api/uploads — raw image upload (§6.4)
  // -------------------------------------------------------------------
  http.post("/api/uploads", async ({ request }) => {
    const formData = await request.formData();
    const file = formData.get("file");

    if (!(file instanceof File)) {
      return apiError(400, {
        error: { code: "corrupt_file", message: "No file was received." },
      });
    }

    const extension = file.name.split(".").pop()?.toLowerCase();
    if (!extension || !ALLOWED_UPLOAD_EXTENSIONS.includes(extension as (typeof ALLOWED_UPLOAD_EXTENSIONS)[number])) {
      return apiError(415, {
        error: {
          code: "unsupported_format",
          message: `"${file.name}" isn't a supported format. Use GeoTIFF/TIFF, or PNG/JPEG for approved benchmark datasets.`,
          details: { filename: file.name },
        },
      });
    }

    const format: UploadResponse["format"] =
      extension === "tif" || extension === "tiff" ? "geotiff" : (extension === "jpg" ? "jpeg" : (extension as "png" | "jpeg"));

    // The mock can't actually read GeoTIFF geo-tags, so it fabricates a
    // location near Luxembourg for .tif/.tiff (simulating "we could detect
    // it") and leaves PNG/JPEG un-georeferenced (simulating a benchmark
    // image with no embedded geodata) — this exercises both branches of
    // the "detected vs. needs manual entry" flow described in DESIGN §4.2.
    // (A real backend could also return the plain "tiff" format value —
    // a TIFF that parses but carries no geo tags — but a mock working off
    // the file extension alone has no way to tell that apart from a true
    // GeoTIFF, so it never produces that value here.)
    const isGeoreferencable = format === "geotiff";

    const response: UploadResponse = {
      fileId: newLocalId("up"),
      originalFilename: file.name,
      format,
      detectedModality: isGeoreferencable ? "optical" : null,
      detectedLocation: isGeoreferencable ? { lat: 49.61, lon: 6.13 } : null,
      detectedTimestamp: isGeoreferencable ? new Date().toISOString().slice(0, 10) : null,
      previewUrl: placeholderPreview(`upload · ${file.name}`, 256, 256),
    };
    return HttpResponse.json(response);
  }),

  // -------------------------------------------------------------------
  // GET /api/patches — footprint layer (§6.5)
  // -------------------------------------------------------------------
  http.get("/api/patches", ({ request }) => {
    // The fixture now holds both regions' full real patch grids (1,616 +
    // 1,814 patches) rather than a handful of mock squares, so — unlike
    // the old always-return-everything mock — the `bbox` query param
    // actually has to narrow the result the way a real spatial index
    // would (DESIGN.md §6.5), or every region select would overlay both
    // countries' patches on top of each other.
    const bboxParam = new URL(request.url).searchParams.get("bbox");
    if (!bboxParam) return HttpResponse.json(MOCK_PATCH_COLLECTION);

    const [minLon, minLat, maxLon, maxLat] = bboxParam.split(",").map(Number);
    const features = MOCK_PATCH_COLLECTION.features.filter(
      (f) =>
        f.properties.lon >= minLon &&
        f.properties.lon <= maxLon &&
        f.properties.lat >= minLat &&
        f.properties.lat <= maxLat,
    );
    return HttpResponse.json({ type: "FeatureCollection", features } satisfies typeof MOCK_PATCH_COLLECTION);
  }),

  // -------------------------------------------------------------------
  // GET /api/patches/:patchId/preview — rendered composite image (§6.6)
  // -------------------------------------------------------------------
  http.get("/api/patches/:patchId/preview", ({ params, request }) => {
    const { patchId } = params;
    const composite = new URL(request.url).searchParams.get("composite") ?? "default_rgb";
    const svg = placeholderSvgString(`${patchId} · ${composite}`);
    return new HttpResponse(svg, { headers: { "Content-Type": "image/svg+xml" } });
  }),

  // -------------------------------------------------------------------
  // GET /api/patches/:patchId/timeseries — temporal browser data (§6.7)
  // -------------------------------------------------------------------
  http.get("/api/patches/:patchId/timeseries", ({ params }) => {
    const patchId = String(params.patchId);
    return HttpResponse.json(mockTimeseriesFor(patchId));
  }),

  // -------------------------------------------------------------------
  // GET /api/reports/:reportId — downloadable report (§6.8)
  // -------------------------------------------------------------------
  http.get("/api/reports/:reportId", ({ params }) => {
    // Real reports are a PDF/JSON produced server-side. The mock returns a
    // small plain-text stand-in so "Download report" is fully clickable
    // end-to-end.
    const body = `SatQuery AI — mock report ${params.reportId}\n\nThis is a placeholder report body. A real orchestrator would attach the full execution trace, evidence images, and answer text here.`;
    return new HttpResponse(body, {
      headers: {
        "Content-Type": "text/plain",
        "Content-Disposition": `attachment; filename="${params.reportId}.txt"`,
      },
    });
  }),

  // -------------------------------------------------------------------
  // Sessions (§8)
  // -------------------------------------------------------------------
  http.get("/api/sessions", () => HttpResponse.json(listSessions())),

  http.get("/api/sessions/:id", ({ params }) => {
    const session = getSession(String(params.id));
    if (!session) {
      return apiError(404, {
        error: { code: "unsupported_task", message: "Session not found." },
      });
    }
    return HttpResponse.json(session);
  }),

  http.post("/api/sessions", () => HttpResponse.json({ id: createSession() })),
];
