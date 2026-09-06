/**
 * components/faq/QuickQuestionsList.tsx
 * =========================================
 * One-click example queries (DESIGN.md §4.5).
 *
 * The list is keyed on the ACTIVE context set's type, so a researcher is
 * never offered a question their current context can't answer — asking
 * "what changed between these two dates" of a single image is a request
 * the orchestrator would have to refuse, and offering it teaches the wrong
 * model of how the tool works.
 *
 * With an empty set the section still renders, with a note. Hiding it
 * entirely (as an earlier revision did) made the panel look like it had
 * fewer features than it does, and gave no hint that filling the context
 * set would reveal them.
 */
import { useContextStore } from "../../state/useContextStore";
import { useChatStore } from "../../state/useChatStore";
import { useSessionStore } from "../../state/useSessionStore";
import type { ContextType } from "../../api/types";

const QUESTIONS_BY_TYPE: Record<ContextType, string[]> = {
  single: [
    "Describe the land-cover and major objects visible in this image.",
    "What vegetation is present, and how healthy does it appear?",
  ],
  cross_modal_pair: ["Use the optical and SAR images together to identify built-up and water-covered regions."],
  bitemporal_pair: [
    "What changed between these two dates, and where did the change occur?",
    "Has the built-up area increased, decreased, or remained unchanged?",
  ],
};

export function QuickQuestionsList() {
  const activeContextSet = useContextStore(
    (s) => s.contextSets.find((c) => c.id === s.activeContextSetId) ?? null,
  );
  const isSending = useChatStore((s) => s.isSending);
  const sendQuery = useChatStore((s) => s.sendQuery);
  const sessionId = useSessionStore((s) => s.sessionId);

  const hasItems = (activeContextSet?.items.length ?? 0) > 0;

  return (
    <section className="flex flex-col gap-[8.4px]">
      <h5 className="text-[14px]">Quick questions</h5>

      {!hasItems || !activeContextSet ? (
        <p className="m-0 text-[11.5px] leading-[1.5] text-neutral-600">
          Questions appear once the active context set has an item — they depend on whether you're asking about one
          image, a pair of dates, or a pair of sensors.
        </p>
      ) : (
        <div className="flex flex-col gap-[5.6px]">
          {QUESTIONS_BY_TYPE[activeContextSet.type].map((question) => (
            <button
              key={question}
              type="button"
              disabled={isSending || !sessionId}
              onClick={() => sessionId && void sendQuery(sessionId, question, activeContextSet)}
              className="btn btn-secondary justify-start px-[8px] py-[6px] text-left text-[12px] font-normal leading-[1.4]"
            >
              {question}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
