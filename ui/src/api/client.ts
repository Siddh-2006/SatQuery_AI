/**
 * api/client.ts
 * ==============
 * The ONLY file in this app that calls `fetch`. Every component/store that
 * needs data from the backend goes through the functions here, never
 * through fetch directly — that keeps the request/response shapes typed
 * against api/types.ts in exactly one place, and means swapping the mock
 * backend (mocks/handlers.ts) for the real orchestrator is just a matter of
 * changing `API_BASE_URL` below (or nothing at all, since both speak the
 * same relative `/api/...` paths and MSW intercepts at the network layer).
 *
 * Every function throws `ApiError` (see api/types.ts) on a non-2xx
 * response, so callers can do:
 *   try { await postQuery(...) } catch (e) { if (e instanceof ApiError) ... }
 */
import {
  ApiError,
  type ApiErrorBody,
  type ChatMessage,
  type ContextSet,
  type PatchFeatureCollection,
  type QueryRequest,
  type QueryResponse,
  type SegmentRequest,
  type SegmentResponse,
  type SessionDetail,
  type SessionSummary,
  type TimeseriesEntry,
  type UploadResponse,
} from "./types";

/** Empty string = same-origin relative paths, which is what MSW intercepts
 *  and what a same-origin production deployment would also want. Once the
 *  real orchestrator (see ../../orchestrator/) is deployed somewhere else
 *  (its own container/host, per orchestrator/DESIGN.md's docker-compose
 *  split), set VITE_API_BASE_URL at build time (see ui/Dockerfile) to
 *  point requests at it — e.g. "http://localhost:8080" for the default
 *  docker-compose layout. Falls back to "" (same-origin) so nothing
 *  changes for anyone still running against MSW or a same-origin proxy. */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
    if (body?.error) throw new ApiError(body);
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Chat / orchestrator (§6.2)
// ---------------------------------------------------------------------------

export async function postQuery(request: QueryRequest): Promise<QueryResponse> {
  const response = await fetch(`${API_BASE_URL}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return parseJsonOrThrow<QueryResponse>(response);
}

// ---------------------------------------------------------------------------
// Segmentation (§6.3)
// ---------------------------------------------------------------------------

export async function postSegment(request: SegmentRequest): Promise<SegmentResponse> {
  const response = await fetch(`${API_BASE_URL}/api/segment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return parseJsonOrThrow<SegmentResponse>(response);
}

// ---------------------------------------------------------------------------
// Upload (§6.4)
// ---------------------------------------------------------------------------

export async function postUpload(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_BASE_URL}/api/uploads`, {
    method: "POST",
    body: formData, // never set Content-Type manually for FormData — the
                     // browser needs to add its own multipart boundary.
  });
  return parseJsonOrThrow<UploadResponse>(response);
}

// ---------------------------------------------------------------------------
// Patches (§6.5-6.7)
// ---------------------------------------------------------------------------

export async function getPatches(bbox?: [number, number, number, number]): Promise<PatchFeatureCollection> {
  const query = bbox ? `?bbox=${bbox.join(",")}` : "";
  const response = await fetch(`${API_BASE_URL}/api/patches${query}`);
  return parseJsonOrThrow<PatchFeatureCollection>(response);
}

/** Not a fetch — just builds the URL an <img> tag should point at, since
 *  this endpoint returns image bytes directly rather than JSON. */
export function patchPreviewUrl(patchId: string, composite: "true_color" | "false_color" | "sar"): string {
  return `${API_BASE_URL}/api/patches/${encodeURIComponent(patchId)}/preview?composite=${composite}`;
}

export async function getPatchTimeseries(patchId: string): Promise<TimeseriesEntry[]> {
  const response = await fetch(`${API_BASE_URL}/api/patches/${encodeURIComponent(patchId)}/timeseries`);
  return parseJsonOrThrow<TimeseriesEntry[]>(response);
}

// ---------------------------------------------------------------------------
// Reports (§6.8)
// ---------------------------------------------------------------------------

/** Same idea as patchPreviewUrl — a direct link target, not a fetch. */
export function reportUrl(reportIdOrPath: string): string {
  // QueryResponse.reportUrl already comes back as a full path (e.g.
  // "/api/reports/rep_abc123"), so we pass it through as-is if so.
  return reportIdOrPath.startsWith("/api/") ? reportIdOrPath : `${API_BASE_URL}/api/reports/${reportIdOrPath}`;
}

// ---------------------------------------------------------------------------
// Sessions (§8)
// ---------------------------------------------------------------------------

export async function listSessions(): Promise<SessionSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/sessions`);
  return parseJsonOrThrow<SessionSummary[]>(response);
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const response = await fetch(`${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}`);
  return parseJsonOrThrow<SessionDetail>(response);
}

export async function createSession(): Promise<{ id: string }> {
  const response = await fetch(`${API_BASE_URL}/api/sessions`, { method: "POST" });
  return parseJsonOrThrow<{ id: string }>(response);
}

// Re-exported only so store files can import everything from one place if
// convenient; not required.
export type { ContextSet, ChatMessage };
