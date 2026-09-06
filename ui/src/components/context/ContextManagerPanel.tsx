/**
 * components/context/ContextManagerPanel.tsx
 * ============================================
 * The context set manager (DESIGN.md §4.1/§4.3): which set is active, what
 * is in it, and the two ways to put something in it that aren't the map
 * (a new set, an upload).
 *
 * The set's TYPE is shown as a tag rather than chosen from a menu, because
 * it is derived, not configured: a set with one item is single, and a
 * second item's pair type is settled by the guardrail at the moment it's
 * added. Showing it as a control would imply a researcher could relabel a
 * bitemporal pair as cross-modal, which is not a thing.
 *
 * The N / 1 or N / 2 counter is there so the capacity is visible before it
 * is reached — the guardrail appearing on the second add should never be a
 * surprise.
 */
import { ContextChip } from "./ContextChip";
import { useContextStore } from "../../state/useContextStore";
import { validateContextSet } from "../../api/validateContextSet";
import type { ContextType } from "../../api/types";

const TYPE_LABEL: Record<ContextType, string> = {
  single: "single",
  cross_modal_pair: "cross-modal pair",
  bitemporal_pair: "bitemporal pair",
};

export function ContextManagerPanel() {
  const contextSets = useContextStore((s) => s.contextSets);
  const activeContextSetId = useContextStore((s) => s.activeContextSetId);
  const setActiveContextSet = useContextStore((s) => s.setActiveContextSet);
  const openUploadDialog = useContextStore((s) => s.openUploadDialog);

  const activeSet = contextSets.find((c) => c.id === activeContextSetId) ?? null;
  const capacity = activeSet?.type === "single" ? 1 : 2;
  // Only worth surfacing once the set is actually full — a half-built pair
  // is "incomplete", not "wrong", and saying so mid-build is noise.
  const validation = activeSet && activeSet.items.length === capacity ? validateContextSet(activeSet) : { valid: true };

  return (
    <section className="flex flex-col gap-[8.4px]">
      <div className="flex items-center gap-[8.4px]">
        <h5 className="text-[14px]">Context manager</h5>
        <button
          type="button"
          onClick={openUploadDialog}
          className="btn btn-primary ml-auto px-[8px] py-[3px] text-[12px]"
        >
          <i className="ph ph-upload-simple text-[12px]" aria-hidden="true" />
          Upload image
        </button>
      </div>

      <div className="flex items-center gap-[5.6px]">
        <label htmlFor="context-set-select" className="sr-only">
          Active context set
        </label>
        {/* No "new empty context set" control here on purpose: a set is
            created automatically the moment something is actually added
            (map footprint, area selection, upload — see
            useContextStore.addItemToActiveSet), so there's never a manually
            spun-up set sitting empty with nothing to show for itself. */}
        <select
          id="context-set-select"
          value={activeContextSetId ?? ""}
          onChange={(event) => setActiveContextSet(event.target.value)}
          disabled={contextSets.length === 0}
          className="input min-h-[30px] text-[12.5px]"
        >
          {contextSets.length === 0 && <option value="">No context sets yet</option>}
          {contextSets.map((contextSet) => (
            <option key={contextSet.id} value={contextSet.id}>
              {contextSet.id} · {TYPE_LABEL[contextSet.type]} · {contextSet.items.length}{" "}
              {contextSet.items.length === 1 ? "item" : "items"}
            </option>
          ))}
        </select>
      </div>

      {activeSet && (
        <div className="card elev-sm">
          <div className="flex items-center gap-[8.4px]">
            <span className="tag tag-accent">{TYPE_LABEL[activeSet.type]}</span>
            <span className="ml-auto text-[11px] tabular-nums text-neutral-500">
              {activeSet.items.length} / {capacity}
            </span>
          </div>

          {activeSet.items.length === 0 ? (
            <p className="m-0 text-[12.5px] leading-[1.5] text-neutral-500">
              No items yet. Pick a footprint on the map, draw an area, or upload an image.
            </p>
          ) : (
            <div className="flex flex-col gap-[5.6px]">
              {activeSet.items.map((item, index) => (
                <ContextChip key={`${activeSet.id}-${index}`} item={item} contextSetId={activeSet.id} index={index} />
              ))}
            </div>
          )}

          {!validation.valid && validation.reason && (
            <p className="m-0 flex items-start gap-[6px] rounded-sm bg-accent-900 px-[8px] py-[6px] text-[11.5px] leading-[1.45] text-accent-200">
              <i className="ph ph-warning-circle mt-[2px] text-[12px]" aria-hidden="true" />
              {validation.reason}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
