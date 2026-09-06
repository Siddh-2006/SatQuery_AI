/**
 * mocks/fixtures/sessions.ts
 * ===========================
 * A tiny in-memory "database" of sessions (DESIGN.md §8), mutated by the
 * MSW handlers as the app creates sessions and appends chat turns. This is
 * intentionally the ONLY piece of mutable module-level state in mocks/ —
 * everything else (patches) is static fixture data. Resets on page reload,
 * which is fine for a mock: real persistence is the backend's job.
 */
import { newLocalId } from "../../lib/id";
import type { ContextSet, ChatMessage, SessionDetail, SessionSummary } from "../../api/types";

const sessionsById = new Map<string, SessionDetail>();

/** Creates a brand-new, empty session and returns its id — backs
 *  POST /api/sessions ("New session", DESIGN.md §8). */
export function createSession(): string {
  const id = newLocalId("sess");
  const now = new Date().toISOString();
  sessionsById.set(id, {
    id,
    title: "Untitled session",
    createdAt: now,
    lastUpdatedAt: now,
    contextSets: [],
    messages: [],
  });
  return id;
}

/** Lists sessions newest-first, for the session switcher's "Load session"
 *  dropdown — backs GET /api/sessions. */
export function listSessions(): SessionSummary[] {
  return [...sessionsById.values()]
    .sort((a, b) => b.lastUpdatedAt.localeCompare(a.lastUpdatedAt))
    .map(({ id, title, createdAt, lastUpdatedAt }) => ({ id, title, createdAt, lastUpdatedAt }));
}

/** Backs GET /api/sessions/:id. */
export function getSession(id: string): SessionDetail | undefined {
  return sessionsById.get(id);
}

/**
 * Appends one user+assistant turn to a session, deriving a title from the
 * first query if the session doesn't have a real one yet (mirrors what a
 * real backend would do server-side). Called by the POST /api/query
 * handler right after it builds the mock answer.
 */
export function appendTurn(
  sessionId: string,
  contextSet: ContextSet,
  userMessage: ChatMessage,
  assistantMessage: ChatMessage,
): void {
  const session = sessionsById.get(sessionId);
  if (!session) return; // unknown/expired session id — nothing to append to

  if (session.title === "Untitled session") {
    session.title = userMessage.text.slice(0, 60);
  }
  if (!session.contextSets.some((c) => c.id === contextSet.id)) {
    session.contextSets.push(contextSet);
  }
  session.messages.push(userMessage, assistantMessage);
  session.lastUpdatedAt = new Date().toISOString();
}
