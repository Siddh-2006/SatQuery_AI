/**
 * App.tsx
 * ========
 * The three-panel shell from DESIGN.md §1: a slim top bar over a row of
 * three panels — context and temporal (left, collapsible), map (centre,
 * flexible), grounded chat (right, collapsible). Nothing scrolls at the
 * document level; each panel scrolls internally.
 *
 * This file wires things together and owns exactly two app-wide concerns
 * nothing else can:
 *
 *  - bootstrap: start a session (§8) and load the footprint layer for the
 *    selected region (§2.1) so the map has something to show immediately.
 *  - the global Escape key. Escape clears every transient thing at once —
 *    popover, pending selection, half-drawn polygon, pairing dialog — and
 *    it is bound here rather than in each tool so the behaviour can't drift
 *    apart between them, and so a tool that has lost focus still responds.
 *
 * The two modals and the toast are mounted at this level, outside the
 * panels, because they are app-scoped: an upload dialog opened from the
 * left panel must not be clipped by the left panel's own overflow.
 */
import { useEffect } from "react";
import { TopBar } from "./components/layout/TopBar";
import { CollapsiblePanel } from "./components/layout/CollapsiblePanel";
import { Toast } from "./components/layout/Toast";
import { MapView } from "./components/map/MapView";
import { ContextManagerPanel } from "./components/context/ContextManagerPanel";
import { TemporalBrowser } from "./components/context/TemporalBrowser";
import { UploadDialog } from "./components/context/UploadDialog";
import { PairTypeDialog } from "./components/context/PairTypeDialog";
import { QuickQuestionsList } from "./components/faq/QuickQuestionsList";
import { ChatPanel } from "./components/chat/ChatPanel";
import { useSessionStore } from "./state/useSessionStore";
import { useMapStore, REGIONS } from "./state/useMapStore";
import { useContextStore } from "./state/useContextStore";
import { useChatStore } from "./state/useChatStore";
import * as api from "./api/client";

export default function App() {
  const sessionId = useSessionStore((s) => s.sessionId);
  const startNewSession = useSessionStore((s) => s.startNewSession);
  const setFootprints = useMapStore((s) => s.setFootprints);
  const region = useMapStore((s) => s.region);
  const clearTransientMapState = useMapStore((s) => s.clearTransientMapState);
  const cancelPairPrompt = useContextStore((s) => s.cancelPairPrompt);
  const messageCount = useChatStore((s) => s.messages.length);

  useEffect(() => {
    if (!sessionId) void startNewSession();
  }, [sessionId, startNewSession]);

  // Footprints are scoped to the selected region's bbox — the same query a
  // real deployment drives from the map viewport. A failed load isn't fatal:
  // the map just renders with no footprints rather than blanking the app.
  useEffect(() => {
    api
      .getPatches(REGIONS[region].bbox)
      .then(setFootprints)
      .catch(() => undefined);
  }, [region, setFootprints]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      clearTransientMapState();
      cancelPairPrompt();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [clearTransientMapState, cancelPairPrompt]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-bg text-ink">
      <TopBar />

      <div className="flex min-h-0 flex-1">
        <CollapsiblePanel
          side="left"
          width={296}
          storageKey="satquery.leftPanelCollapsed"
          title="Context & temporal"
          railIcons={["ph-stack", "ph-clock-counter-clockwise", "ph-question"]}
          railLabel="Context"
        >
          <div className="flex flex-col gap-[16.8px] px-[11.2px] pb-[16.8px]">
            <ContextManagerPanel />
            <TemporalBrowser />
            <QuickQuestionsList />
          </div>
        </CollapsiblePanel>

        <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
          <MapView />
        </main>

        <CollapsiblePanel
          side="right"
          width={376}
          storageKey="satquery.rightPanelCollapsed"
          title="Grounded chat"
          railIcons={["ph-chat-teardrop-text"]}
          railLabel="Chat"
          railBadge={messageCount > 0 ? String(messageCount) : undefined}
          scroll={false}
        >
          <ChatPanel />
        </CollapsiblePanel>
      </div>

      <UploadDialog />
      <PairTypeDialog />
      <Toast />
    </div>
  );
}
