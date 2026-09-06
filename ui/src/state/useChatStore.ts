/**
 * state/useChatStore.ts
 * =======================
 * The chat thread for the current session (DESIGN.md §3), plus the one
 * piece of state that ties an answer's grounded text to its visual
 * evidence: `hoveredEvidenceId` (§3.2). Both the chat components (which
 * highlight a span on hover) and the map/drawer overlay components (which
 * highlight the matching bbox/mask) read this same value, so hovering
 * either side lights up the other without any direct coupling between
 * those component trees.
 */
import { create } from "zustand";
import { ApiError, type ChatMessage, type ContextSet, type GroundingPreference } from "../api/types";
import { postQuery } from "../api/client";
import { newLocalId } from "../lib/id";

interface ChatState {
  messages: ChatMessage[];
  isSending: boolean;
  /** Set when the last send failed; cleared on the next successful send.
   *  Shown inline near the prompt input rather than as a generic toast, so
   *  it stays next to the thing the user needs to fix (DESIGN.md §6.9). */
  lastError: string | null;

  /** What the user wants the *next* answer's evidence shaped like (§3.3).
   *  Purely a request — the orchestrator may return a different kind if
   *  the selected specialist model can't produce that form. */
  groundingPreference: GroundingPreference;
  setGroundingPreference: (pref: GroundingPreference) => void;

  hoveredEvidenceId: string | null;
  setHoveredEvidenceId: (id: string | null) => void;

  /** Sends `query` against `contextSet` within `sessionId`, appending both
   *  the user's message and the assistant's reply to the thread. Throws
   *  nothing — failures are recorded in `lastError` for the UI to render. */
  sendQuery: (sessionId: string, query: string, contextSet: ContextSet) => Promise<void>;

  hydrate: (messages: ChatMessage[]) => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isSending: false,
  lastError: null,

  groundingPreference: "auto",
  setGroundingPreference: (pref) => set({ groundingPreference: pref }),

  hoveredEvidenceId: null,
  setHoveredEvidenceId: (id) => set({ hoveredEvidenceId: id }),

  sendQuery: async (sessionId, query, contextSet) => {
    const userMessage: ChatMessage = {
      id: newLocalId("msg"),
      role: "user",
      text: query,
      contextSetId: contextSet.id,
      createdAt: new Date().toISOString(),
    };
    set((s) => ({ messages: [...s.messages, userMessage], isSending: true, lastError: null }));

    try {
      const response = await postQuery({
        sessionId,
        query,
        contextSet,
        groundingPreference: get().groundingPreference,
      });
      const assistantMessage: ChatMessage = {
        id: newLocalId("msg"),
        role: "assistant",
        text: response.answer,
        groundedSpans: response.groundedSpans,
        evidence: response.evidence,
        confidence: response.confidence,
        executionTrace: response.executionTrace,
        reportUrl: response.reportUrl,
        contextSetId: contextSet.id,
        createdAt: new Date().toISOString(),
      };
      set((s) => ({ messages: [...s.messages, assistantMessage], isSending: false }));
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Something went wrong sending that query.";
      set({ isSending: false, lastError: message });
    }
  },

  hydrate: (messages) => set({ messages, lastError: null }),
  reset: () => set({ messages: [], lastError: null, hoveredEvidenceId: null }),
}));
