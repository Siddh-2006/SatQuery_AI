/**
 * components/layout/SessionSwitcher.tsx
 * ========================================
 * The top-bar session control (DESIGN.md §8): the current session's title,
 * a "New" button, and a dropdown of past sessions to load. All three
 * actions already exist on useSessionStore — this component is deliberately
 * thin.
 *
 * The past-session list is fetched lazily, the first time the menu opens,
 * because most sessions never open it and the list is worthless until then.
 */
import { useEffect, useRef, useState } from "react";
import { useSessionStore } from "../../state/useSessionStore";
import { useToastStore } from "../../state/useToastStore";

/** "2 days ago" / "Aug 28" — session lists are scanned, not read, so a
 *  relative label for anything recent beats a full timestamp. */
function relativeDate(iso: string): string {
  const date = new Date(iso);
  const days = Math.round((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function SessionSwitcher() {
  const { sessionId, title, pastSessions, isLoadingList, startNewSession, refreshSessionList, loadSession } =
    useSessionStore();
  const showToast = useToastStore((s) => s.show);
  const [menuOpen, setMenuOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Click-away close. Registered only while the menu is open so the app
  // isn't listening on every document click for no reason.
  useEffect(() => {
    if (!menuOpen) return;
    function handlePointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [menuOpen]);

  async function handleToggleMenu() {
    const opening = !menuOpen;
    setMenuOpen(opening);
    if (opening && !pastSessions) await refreshSessionList();
  }

  return (
    <div ref={containerRef} className="relative flex items-center gap-[8.4px]">
      <button
        type="button"
        onClick={() => void handleToggleMenu()}
        title={sessionId ?? undefined}
        aria-expanded={menuOpen}
        className="btn btn-secondary max-w-[280px] text-[13px]"
      >
        <span className="truncate">{title}</span>
        <i className="ph ph-caret-down text-[12px]" aria-hidden="true" />
      </button>

      <button
        type="button"
        onClick={() => {
          void startNewSession();
          setMenuOpen(false);
          showToast("Started a new session");
        }}
        className="btn btn-primary text-[13px]"
      >
        <i className="ph ph-plus text-[12px]" aria-hidden="true" />
        New
      </button>

      {menuOpen && (
        <div className="card elev-md absolute left-0 top-[42px] z-[60] w-[320px] gap-[5.6px]">
          <span className="card-kicker">Load session</span>

          {isLoadingList && <div className="text-[12.5px] text-neutral-500">Loading…</div>}
          {!isLoadingList && pastSessions?.length === 0 && (
            <div className="text-[12.5px] text-neutral-500">No past sessions yet.</div>
          )}

          {!isLoadingList &&
            pastSessions?.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => {
                  void loadSession(session.id);
                  setMenuOpen(false);
                  showToast("Session loaded");
                }}
                className="flex w-full flex-col items-start gap-[1px] rounded-sm border-0 bg-transparent px-[5.6px] py-[5.6px] text-left hover:bg-[color-mix(in_srgb,var(--color-text)_7%,transparent)]"
              >
                <span className="w-full truncate text-[13px] text-ink">{session.title}</span>
                <span className="text-[11px] text-neutral-500">
                  {session.id} · {relativeDate(session.lastUpdatedAt)}
                </span>
              </button>
            ))}

          <span className="text-[11px] text-neutral-500">GET /api/sessions · newest first</span>
        </div>
      )}
    </div>
  );
}
