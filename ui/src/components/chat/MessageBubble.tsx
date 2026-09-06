/**
 * components/chat/MessageBubble.tsx
 * ==================================
 * One turn in the thread (DESIGN.md §3.1). A user message is a tinted
 * bubble; an assistant message is a card carrying four things the answer
 * text alone can't convey:
 *
 *  1. the grounded answer (GroundedText),
 *  2. a confidence figure, shown as a bar AND a number — the bar for
 *     glancing, the number because "roughly two thirds" is not a thing a
 *     researcher can cite,
 *  3. the execution trace, collapsed,
 *  4. what grounding actually came back, as a tag — which may not be what
 *     was asked for (see GroundingModeDropdown).
 *
 * Trace expansion is local state: it's about this card on this screen, not
 * something a session should remember or another component should read.
 */
import { useState } from "react";
import { GroundedText } from "./GroundedText";
import { ExecutionTraceAccordion } from "./ExecutionTraceAccordion";
import { ReportDownloadButton } from "./ReportDownloadButton";
import type { ChatMessage } from "../../api/types";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const [traceOpen, setTraceOpen] = useState(false);

  if (message.role === "user") {
    return (
      <div className="max-w-[90%] self-end rounded-md bg-accent-900 px-[11px] py-[7px] text-[13px] leading-[1.5]">
        {message.text}
      </div>
    );
  }

  const confidence = message.confidence ?? 0;
  const groundingKind = message.evidence?.[0]?.kind;

  return (
    <div className="card elev-sm gap-[8.4px]">
      <span className="card-kicker">Assistant</span>

      <p className="m-0 text-[13.5px] leading-[1.65]">
        <GroundedText text={message.text} spans={message.groundedSpans} />
      </p>

      {message.confidence !== undefined && (
        <div className="flex items-center gap-[8.4px]">
          <span className="flex-none text-[11px] text-neutral-500">Confidence</span>
          <div className="h-[5px] min-w-0 flex-1 overflow-hidden rounded-[3px] bg-neutral-900">
            <div className="h-full rounded-[3px] bg-accent" style={{ width: `${confidence * 100}%` }} />
          </div>
          <span className="flex-none text-[11.5px] tabular-nums">{Math.round(confidence * 100)}%</span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-[5.6px]">
        {message.executionTrace && (
          <button
            type="button"
            onClick={() => setTraceOpen((open) => !open)}
            aria-expanded={traceOpen}
            className="btn btn-secondary text-[12px]"
          >
            <i className={`ph ${traceOpen ? "ph-caret-down" : "ph-caret-right"} text-[11px]`} aria-hidden="true" />
            Execution trace
          </button>
        )}
        {message.reportUrl && <ReportDownloadButton url={message.reportUrl} />}
        {groundingKind && (
          <span className="tag tag-outline ml-auto">
            {groundingKind === "mask" ? "mask returned" : groundingKind === "bbox" ? "bbox returned" : "point returned"}
          </span>
        )}
      </div>

      {traceOpen && message.executionTrace && <ExecutionTraceAccordion trace={message.executionTrace} />}
    </div>
  );
}
