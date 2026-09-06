/**
 * components/chat/GroundingModeDropdown.tsx
 * ===========================================
 * What shape the researcher would PREFER the next answer's evidence to
 * take (DESIGN.md §3.3): let the orchestrator decide, a bounding box, or a
 * segmentation mask.
 *
 * A request, not a setting. The orchestrator routes to whichever specialist
 * model fits the question, and that model may only be able to produce one
 * form — so the answer card states what actually came back ("mask
 * returned" / "bbox returned") rather than this control pretending to have
 * guaranteed it. The copy here says "Auto (let orchestrator decide)" for
 * the same reason.
 */
import { useChatStore } from "../../state/useChatStore";
import type { GroundingPreference } from "../../api/types";

const OPTIONS: { value: GroundingPreference; label: string }[] = [
  { value: "auto", label: "Auto (let orchestrator decide)" },
  { value: "bbox", label: "Bounding box" },
  { value: "mask", label: "Segmentation mask" },
];

export function GroundingModeDropdown() {
  const groundingPreference = useChatStore((s) => s.groundingPreference);
  const setGroundingPreference = useChatStore((s) => s.setGroundingPreference);

  return (
    <div className="flex items-center gap-[8.4px]">
      <label htmlFor="grounding-mode" className="flex-none text-[11px] text-neutral-500">
        Grounding
      </label>
      <select
        id="grounding-mode"
        value={groundingPreference}
        onChange={(event) => setGroundingPreference(event.target.value as GroundingPreference)}
        className="input min-h-[30px] text-[12.5px]"
      >
        {OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
