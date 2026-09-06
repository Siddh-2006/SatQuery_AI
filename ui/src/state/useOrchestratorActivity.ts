/**
 * state/useOrchestratorActivity.ts
 * ===================================
 * ADDITIVE, OPTIONAL hook — not part of DESIGN.md's documented API
 * contract. Subscribes to the orchestrator's live "what am I doing right
 * now" feed (`GET /api/sessions/:id/activity`, an SSE endpoint — see
 * orchestrator/DESIGN.md §7) while a query is in flight, so the chat panel
 * can show something more specific than a generic spinner (e.g. "Calling
 * query_eocaptioner…" instead of just "thinking").
 *
 * Deliberately fails silent: if this endpoint doesn't exist (an older
 * backend, or the mock server) or the connection drops, `activityDetail`
 * just stays null and the caller falls back to its own generic message —
 * this hook must never be the thing that makes the chat panel look broken.
 */
import { useEffect, useState } from "react";

export function useOrchestratorActivity(sessionId: string | null, isActive: boolean): string | null {
  const [detail, setDetail] = useState<string | null>(null);

  useEffect(() => {
    if (!isActive || !sessionId) {
      setDetail(null);
      return;
    }

    const base = import.meta.env.VITE_API_BASE_URL ?? "";
    const source = new EventSource(`${base}/api/sessions/${encodeURIComponent(sessionId)}/activity`);

    source.addEventListener("status", (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data) as { step: string; detail: string };
        setDetail(data.detail || data.step);
      } catch {
        // Malformed event — ignore rather than crash the chat panel over a status line.
      }
    });
    source.addEventListener("done", () => setDetail(null));
    // No-op on error rather than surfacing it: this feed is a nice-to-have,
    // never the thing a failed query should be blamed on.
    source.onerror = () => {};

    return () => source.close();
  }, [sessionId, isActive]);

  return detail;
}
