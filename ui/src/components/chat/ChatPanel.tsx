/**
 * components/chat/ChatPanel.tsx
 * ===============================
 * The right panel (DESIGN.md §3): the thread, the prompt, and the one
 * status line that explains why the prompt is or isn't usable.
 *
 * The prompt is disabled until the active context set holds an item, and
 * the status line says so in words. This is the app's central constraint —
 * every answer is grounded in specific imagery, so there is no such thing
 * as a question without a context set — and it is cheaper to state it than
 * to let someone type a paragraph into a field that will reject it.
 *
 * When the set IS usable, the same line names exactly what will be sent:
 * which context set, its type, and the grounding preference. A researcher
 * writing up results needs to know what a given answer was asked against,
 * and the moment to tell them is before they ask.
 *
 * Enter sends; Shift+Enter makes a newline. Server errors appear inline
 * above the prompt (never as a toast) because the researcher has to act on
 * them — see api/types.ts on ApiErrorBody.message being safe to show.
 */
import { useEffect, useRef, useState } from "react";
import { MessageBubble } from "./MessageBubble";
import { GroundingModeDropdown } from "./GroundingModeDropdown";
import { useChatStore } from "../../state/useChatStore";
import { useContextStore } from "../../state/useContextStore";
import { useSessionStore } from "../../state/useSessionStore";
import { useOrchestratorActivity } from "../../state/useOrchestratorActivity";
import { validateContextSet } from "../../api/validateContextSet";

const CONTEXT_TYPE_LABEL: Record<string, string> = {
  single: "single",
  cross_modal_pair: "cross-modal pair",
  bitemporal_pair: "bitemporal pair",
};

export function ChatPanel() {
  const messages = useChatStore((s) => s.messages);
  const isSending = useChatStore((s) => s.isSending);
  const lastError = useChatStore((s) => s.lastError);
  const groundingPreference = useChatStore((s) => s.groundingPreference);
  const sendQuery = useChatStore((s) => s.sendQuery);
  const activeContextSet = useContextStore(
    (s) => s.contextSets.find((c) => c.id === s.activeContextSetId) ?? null,
  );
  const sessionId = useSessionStore((s) => s.sessionId);
  // Optional live "what is it doing" line from the real orchestrator
  // (orchestrator/DESIGN.md §7) — null (and silently ignored) against the
  // MSW mock or an older backend that doesn't expose this feed.
  const activityDetail = useOrchestratorActivity(sessionId, isSending);

  const [draft, setDraft] = useState("");
  const threadRef = useRef<HTMLDivElement | null>(null);

  const hasItems = (activeContextSet?.items.length ?? 0) > 0;
  const validation = activeContextSet ? validateContextSet(activeContextSet) : { valid: false };
  const canSend = hasItems && !isSending && Boolean(sessionId);

  // Pin to the newest turn on every new message and on the loading flip —
  // assigning scrollTop rather than scrolling an element into view, so the
  // panel scrolls and the surrounding layout never does.
  useEffect(() => {
    const thread = threadRef.current;
    if (thread) thread.scrollTop = thread.scrollHeight;
  }, [messages.length, isSending]);

  function handleSend() {
    const query = draft.trim();
    if (!query || !canSend || !activeContextSet || !sessionId) return;
    setDraft("");
    void sendQuery(sessionId, query, activeContextSet);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={threadRef} className="flex min-h-0 flex-1 flex-col gap-[11.2px] overflow-y-auto px-[11.2px] pb-[11.2px]">
        {messages.length === 0 && !isSending && (
          <div className="my-auto flex flex-col items-start gap-[8.4px] py-[22.4px]">
            <i className="ph ph-crosshair text-[22px] text-accent" aria-hidden="true" />
            <h4 className="font-heading text-[16px] font-medium">Nothing asked yet</h4>
            <p className="m-0 text-[12.5px] leading-[1.6] text-neutral-500">
              Every answer comes back with grounded spans, a confidence figure, the execution trace and a downloadable
              report. Select a patch to enable the prompt.
            </p>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {isSending && (
          <div className="card elev-sm">
            <span className="animate-sq-pulse text-[12.5px] text-neutral-400">
              {activityDetail ?? "Orchestrator routing the query…"}
            </span>
          </div>
        )}
      </div>

      <div
        className="flex flex-none flex-col gap-[8.4px] p-[11.2px]"
        style={{ boxShadow: "0 -1px 0 var(--color-divider)" }}
      >
        <GroundingModeDropdown />

        {lastError && (
          <p className="m-0 flex items-start gap-[6px] rounded-sm bg-accent-900 px-[8px] py-[6px] text-[11.5px] leading-[1.45] text-accent-200">
            <i className="ph ph-warning-circle mt-[2px] text-[12px]" aria-hidden="true" />
            {lastError}
          </p>
        )}

        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
          disabled={!canSend}
          placeholder={hasItems ? "Ask about the selected imagery…" : "Select a patch on the map to begin"}
          className="input min-h-[66px] resize-none text-[13px]"
        />

        <div className="flex items-end gap-[8.4px]">
          <p className="m-0 min-w-0 flex-1 text-[11px] leading-[1.45] text-neutral-600">
            {!hasItems
              ? "Prompt disabled until the active context set has an item."
              : `Sends contextSet ${activeContextSet?.id} (${CONTEXT_TYPE_LABEL[activeContextSet?.type ?? "single"]}) · groundingPreference: ${groundingPreference}`}
            {hasItems && !validation.valid && validation.reason ? ` · ${validation.reason}` : ""}
          </p>
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend || draft.trim().length === 0}
            className="btn btn-primary flex-none text-[13px]"
          >
            <i className="ph ph-paper-plane-right text-[12px]" aria-hidden="true" />
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
