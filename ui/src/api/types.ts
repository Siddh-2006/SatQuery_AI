/**
 * api/types.ts
 * =============
 * The single source of truth for every shape that crosses the network
 * boundary between this frontend and the orchestrator backend.
 *
 * This file is a direct, literal transcription of DESIGN.md Section 6
 * ("API contract"). If you change a shape here, update DESIGN.md to match
 * (and vice versa) — the two must never drift apart. Both the real
 * `api/client.ts` and the mock handlers in `mocks/handlers.ts` import
 * exclusively from this file, so the mock cannot silently diverge from
 * what the real backend is expected to return.
 *
 * Nothing in this file talks to the network itself — it's pure types plus
 * the tiny set of string-literal unions the rest of the app switches on.
 */

// ---------------------------------------------------------------------------
// Core enums / literal unions
// ---------------------------------------------------------------------------

/** Which sensor a piece of imagery comes from. */
export type Modality = "optical" | "sar";

/** How much of a patch's band data to pull into context (DESIGN.md §2.3). */
export type BandSelection = "default_rgb" | "sar_only" | "full_bands";

/**
 * The three input shapes the problem statement defines. Every ContextSet
 * is exactly one of these — see DESIGN.md §4.1 for why this is a closed
 * set rather than a freeform list of images.
 */
export type ContextType = "single" | "cross_modal_pair" | "bitemporal_pair";

/** Which map tool produced a pending/confirmed area selection (§2.2). */
export type SelectionMethod = "footprint" | "free_draw" | "point_segment";

// ---------------------------------------------------------------------------
// Context items — the three ways a piece of imagery enters a ContextSet
// ---------------------------------------------------------------------------

/**
 * A whole, unambiguous dataset patch already in our indexed footprints
 * (BigEarthNet-derived Sentinel-1/2 tiles). Produced by the "footprint
 * select" map tool (§2.3).
 */
export interface PatchRef {
  kind: "patch";
  /** Stable id in our patch index, e.g. "LUX-0417". */
  patchId: string;
  lat: number;
  lon: number;
  /** ISO 8601 capture date. */
  timestamp: string;
  availableModalities: Modality[];
  bandSelection: BandSelection;
}

/**
 * A user-drawn polygon or a model-segmented mask — see §2.4/§2.5. Only
 * valid inside a "single" ContextSet in v1 (DESIGN.md §4.1) because it may
 * span more than one underlying patch, which cross-modal/bitemporal pairing
 * isn't designed to handle yet.
 */
export interface AreaSelectionRef {
  kind: "area_selection";
  method: Extract<SelectionMethod, "free_draw" | "point_segment">;
  /** Exact for free_draw; the model's mask outline for point_segment. */
  geometry: GeoJSON.Polygon | GeoJSON.Point;
  /** Every patch this selection overlaps — always sent, never inferred. */
  resolvedPatchIds: string[];
  /** = resolvedPatchIds.length, kept explicit for convenience/logging. */
  patchCount: number;
  /** Present only when method === "point_segment". */
  segmentationConfidence?: number;
}

/**
 * A researcher-supplied image (GeoTIFF/TIFF, or PNG/JPEG restricted to
 * approved benchmark datasets) that isn't in our indexed footprints — see
 * §4.2. Unlike AreaSelectionRef, this CAN go into any ContextType; an
 * upload with no detected location is limited to "single" only because the
 * pairing rules need a location to match on, not because of an arbitrary
 * restriction.
 */
export interface UploadedImageRef {
  kind: "uploaded_image";
  /** Id returned by POST /api/uploads. */
  fileId: string;
  originalFilename: string;
  format: "geotiff" | "tiff" | "png" | "jpeg";
  detectedModality: Modality | null;
  detectedLocation: { lat: number; lon: number } | null;
  detectedTimestamp: string | null;
  /** Server-rendered thumbnail — never decoded client-side. */
  previewUrl: string;
}

/** A context set's items are always one of these three. */
export type ContextItem = PatchRef | AreaSelectionRef | UploadedImageRef;

/**
 * One typed bundle of imagery to reason over. `items.length` is 1 for
 * "single", 2 for both pair types (patch and/or uploaded_image, sharing a
 * location — enforced client-side in api/client.ts's validateContextSet,
 * and authoritatively on the server).
 */
export interface ContextSet {
  id: string;
  type: ContextType;
  items: ContextItem[];
}

// ---------------------------------------------------------------------------
// Grounding & execution trace — what comes back with an answer
// ---------------------------------------------------------------------------

/**
 * One piece of visual evidence backing part of an answer. `id` is shared
 * with a `groundedSpans[].evidenceId` in the same response so the chat
 * text and the map/drawer overlay can be hover-linked (§3.2).
 */
export interface GroundingEvidence {
  id: string;
  /** Which patch this overlay belongs to. */
  patchId: string;
  kind: "bbox" | "mask" | "point";
  /**
   * bbox: [xMin, yMin, xMax, yMax] in the patch's pixel space.
   * mask: a URL string, pointing to a PNG mask aligned to the patch preview.
   * point: [x, y] in the patch's pixel space.
   */
  geometry: number[] | string;
  label: string;
}

/** A grounded run of characters in an answer, linked to one evidence item. */
export interface GroundedSpan {
  start: number;
  end: number;
  evidenceId: string;
}

/**
 * The PS's mandatory "auditable execution summary" — rendered as-is in the
 * chat's Execution Trace accordion (§3.4), never interpreted client-side.
 */
export interface ExecutionTrace {
  /** e.g. "change_vqa", "cross_modal_fusion", "vqa". */
  task: string;
  modelsUsed: { name: string; role: string }[];
  parameters: Record<string, unknown>;
}

/** What the user asks the orchestrator to prefer for the next answer's
 *  visual evidence — a request, not a guarantee (§3.3). */
export type GroundingPreference = "auto" | "bbox" | "mask";

// ---------------------------------------------------------------------------
// POST /api/query
// ---------------------------------------------------------------------------

export interface QueryRequest {
  sessionId: string;
  query: string;
  contextSet: ContextSet;
  groundingPreference: GroundingPreference;
}

export interface QueryResponse {
  answer: string;
  groundedSpans: GroundedSpan[];
  evidence: GroundingEvidence[];
  /** 0..1 */
  confidence: number;
  executionTrace: ExecutionTrace;
  /** Fetch via GET /api/reports/:reportId to download. */
  reportUrl: string;
}

// ---------------------------------------------------------------------------
// POST /api/segment
// ---------------------------------------------------------------------------

export interface SegmentRequest {
  point: { lat: number; lon: number };
  /** Set when the click happened inside the Patch Viewer for a known patch. */
  patchIdHint?: string;
}

export interface SegmentResponse {
  geometry: GeoJSON.Polygon;
  resolvedPatchIds: string[];
  confidence: number;
  modelUsed: string;
}

// ---------------------------------------------------------------------------
// POST /api/uploads
// ---------------------------------------------------------------------------

export interface UploadResponse {
  fileId: string;
  originalFilename: string;
  format: UploadedImageRef["format"];
  detectedModality: Modality | null;
  detectedLocation: { lat: number; lon: number } | null;
  detectedTimestamp: string | null;
  previewUrl: string;
}

// ---------------------------------------------------------------------------
// GET /api/patches
// ---------------------------------------------------------------------------

/** One footprint feature's properties, as returned inside the
 *  FeatureCollection from GET /api/patches. */
export interface PatchFeatureProperties {
  patchId: string;
  lat: number;
  lon: number;
  availableModalities: Modality[];
  availableTimestamps: string[];
  /** Short human label shown in the popover, e.g. "Luxembourg City area". */
  label: string;
}

export type PatchFeatureCollection = GeoJSON.FeatureCollection<
  GeoJSON.Polygon,
  PatchFeatureProperties
>;

/** GET /api/patches/:id/timeseries — every known capture at that patch's
 *  location, for the temporal browser (§4.4). */
export interface TimeseriesEntry {
  patchId: string;
  timestamp: string;
  thumbnailUrl: string;
}

// ---------------------------------------------------------------------------
// Sessions (§8)
// ---------------------------------------------------------------------------

export interface SessionSummary {
  id: string;
  /** Derived server-side, e.g. from the first query in the session. */
  title: string;
  createdAt: string;
  lastUpdatedAt: string;
}

/** One turn of the conversation, as rendered in the chat panel (§3.1). */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Only present on assistant messages. */
  groundedSpans?: GroundedSpan[];
  evidence?: GroundingEvidence[];
  confidence?: number;
  executionTrace?: ExecutionTrace;
  reportUrl?: string;
  /** Which context set was active when this message was sent. */
  contextSetId: string;
  createdAt: string;
}

export interface SessionDetail extends SessionSummary {
  contextSets: ContextSet[];
  messages: ChatMessage[];
}

// ---------------------------------------------------------------------------
// Errors (§6.9) — every endpoint returns this shape on failure
// ---------------------------------------------------------------------------

export type ApiErrorCode =
  | "incompatible_context"
  | "unsupported_task"
  | "segmentation_failed"
  | "unsupported_format"
  | "corrupt_file"
  | "model_error";

export interface ApiErrorBody {
  error: {
    code: ApiErrorCode;
    /** Safe to show to the user as-is. */
    message: string;
    details?: Record<string, unknown>;
  };
}

/** Thrown by api/client.ts whenever a request comes back non-2xx, so
 *  callers can `catch (e) { if (e instanceof ApiError) ... }`. */
export class ApiError extends Error {
  code: ApiErrorCode;
  details?: Record<string, unknown>;

  constructor(body: ApiErrorBody) {
    super(body.error.message);
    this.name = "ApiError";
    this.code = body.error.code;
    this.details = body.error.details;
  }
}
