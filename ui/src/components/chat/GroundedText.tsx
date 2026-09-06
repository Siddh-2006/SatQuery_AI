/**
 * components/chat/GroundedText.tsx
 * ==================================
 * Renders an answer with its grounded spans marked (DESIGN.md §3.2).
 *
 * A span is not an annotation on the text — it is the link between a claim
 * and the pixels backing it. Hovering one sets `hoveredEvidenceId` on the
 * chat store, which the patch viewer's overlay reads, so pointing at "an
 * agricultural field" lights up the box the model drew around it. That one
 * shared primitive is the whole grounding UI; nothing else coordinates the
 * two panels.
 *
 * Spans are given as character offsets into the answer, so this walks the
 * string once and emits alternating plain and grounded runs. Overlapping or
 * out-of-order spans are not supported and are not expected: the contract
 * (§6.1) is non-overlapping ranges. Sorting defensively costs nothing and
 * means a malformed response degrades to plain text rather than throwing.
 *
 * The superscript marker is numbered by span order, matching nothing else
 * in the UI on purpose — it exists so a researcher can refer to "the second
 * grounded claim" in writing, not to index into the evidence array.
 */
import { useChatStore } from "../../state/useChatStore";
import type { GroundedSpan } from "../../api/types";

interface GroundedTextProps {
  text: string;
  spans?: GroundedSpan[];
}

export function GroundedText({ text, spans }: GroundedTextProps) {
  const hoveredEvidenceId = useChatStore((s) => s.hoveredEvidenceId);
  const setHoveredEvidenceId = useChatStore((s) => s.setHoveredEvidenceId);

  if (!spans?.length) return <>{text}</>;

  const ordered = [...spans].sort((a, b) => a.start - b.start);
  const runs: React.ReactNode[] = [];
  let cursor = 0;

  ordered.forEach((span, index) => {
    if (span.start < cursor || span.end > text.length) return; // malformed — skip
    if (span.start > cursor) runs.push(text.slice(cursor, span.start));

    const isHot = hoveredEvidenceId === span.evidenceId;
    runs.push(
      <span
        key={`${span.evidenceId}-${span.start}`}
        onMouseEnter={() => setHoveredEvidenceId(span.evidenceId)}
        onMouseLeave={() => setHoveredEvidenceId(null)}
        className="cursor-pointer rounded-[3px] px-[2px]"
        style={{
          background: isHot ? "rgba(145,132,217,.45)" : "rgba(145,132,217,.22)",
          boxShadow: "inset 0 -1px 0 var(--color-accent)",
        }}
      >
        {text.slice(span.start, span.end)}
        <sup className="ml-[1px] text-[9px] text-accent-300">{index + 1}</sup>
      </span>,
    );
    cursor = span.end;
  });

  if (cursor < text.length) runs.push(text.slice(cursor));
  return <>{runs}</>;
}
