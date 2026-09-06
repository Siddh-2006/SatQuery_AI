/**
 * state/useSessionStore.ts
 * ==========================
 * Backs the session switcher in the top bar (DESIGN.md §8): which session
 * is current, the list of past sessions to pick from, and the three
 * actions (continue is implicit — just keep using the current session id;
 * new; load) that reset or hydrate useContextStore/useChatStore together.
 *
 * This store is the one place allowed to reach into the other two stores'
 * `getState()` directly (rather than being used via a hook) — it's
 * explicitly an orchestration layer above them, not a component.
 */
import { create } from "zustand";
import * as api from "../api/client";
import type { SessionSummary } from "../api/types";
import { useContextStore } from "./useContextStore";
import { useChatStore } from "./useChatStore";

interface SessionState {
  sessionId: string | null;
  title: string;

  /** Loaded lazily the first time the switcher's dropdown opens; null
   *  means "not fetched yet", not "empty". */
  pastSessions: SessionSummary[] | null;
  isLoadingList: boolean;

  /** Creates a fresh session on the backend and clears context+chat.
   *  Called once on app boot, and again whenever the user clicks
   *  "New session". */
  startNewSession: () => Promise<void>;

  /** Fetches the past-sessions list for the switcher dropdown. */
  refreshSessionList: () => Promise<void>;

  /** Loads a past session's full state and replaces the current
   *  context+chat with it. */
  loadSession: (id: string) => Promise<void>;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessionId: null,
  title: "Untitled session",
  pastSessions: null,
  isLoadingList: false,

  startNewSession: async () => {
    const { id } = await api.createSession();
    useContextStore.getState().reset();
    useChatStore.getState().reset();
    set({ sessionId: id, title: "Untitled session" });
  },

  refreshSessionList: async () => {
    set({ isLoadingList: true });
    try {
      const sessions = await api.listSessions();
      set({ pastSessions: sessions, isLoadingList: false });
    } catch {
      set({ isLoadingList: false });
    }
  },

  loadSession: async (id) => {
    const detail = await api.getSession(id);
    // (Array.prototype.at() needs ES2022 lib; tsconfig targets ES2020, so
    // index from the end manually instead of bumping the lib target just
    // for this one call.)
    const activeContextSetId = detail.contextSets[detail.contextSets.length - 1]?.id ?? null;
    useContextStore.getState().hydrate(detail.contextSets, activeContextSetId);
    useChatStore.getState().hydrate(detail.messages);
    set({ sessionId: detail.id, title: detail.title });
  },
}));
