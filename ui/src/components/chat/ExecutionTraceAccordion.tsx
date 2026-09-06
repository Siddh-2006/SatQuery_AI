/**
 * components/chat/ExecutionTraceAccordion.tsx
 * =============================================
 * The auditable execution summary the problem statement requires
 * (DESIGN.md §3.4): which task the orchestrator routed to, which models
 * ran and in what role, and the parameters they ran with.
 *
 * Rendered AS-IS. Nothing here interprets, relabels, prettifies or filters
 * the trace — parameter keys appear exactly as the backend named them, in
 * a monospace face, because the point of an audit trail is that it matches
 * what actually ran. If a value looks wrong, that is information.
 *
 * Collapsed by default: it's evidence to check, not something to read on
 * every answer.
 */
import type { ExecutionTrace } from "../../api/types";

interface ExecutionTraceAccordionProps {
  trace: ExecutionTrace;
}

function TraceRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-[8.4px]">
      <span className="w-[78px] flex-none text-neutral-500">{label}</span>
      <span className="min-w-0 flex-1 break-words font-mono">{children}</span>
    </div>
  );
}

export function ExecutionTraceAccordion({ trace }: ExecutionTraceAccordionProps) {
  return (
    <div className="flex flex-col gap-[5.6px] rounded-sm bg-neutral-900 p-[8.4px] text-[12px]">
      <TraceRow label="task">{trace.task}</TraceRow>

      {trace.modelsUsed.map((model) => (
        <TraceRow key={`${model.name}-${model.role}`} label="model">
          {model.name} — {model.role}
        </TraceRow>
      ))}

      {Object.entries(trace.parameters).map(([key, value]) => (
        <TraceRow key={key} label={key}>
          {typeof value === "object" ? JSON.stringify(value) : String(value)}
        </TraceRow>
      ))}

      <p className="m-0 mt-[2.8px] text-[11px] text-neutral-600">
        Rendered as-is from executionTrace — no client-side interpretation.
      </p>
    </div>
  );
}
