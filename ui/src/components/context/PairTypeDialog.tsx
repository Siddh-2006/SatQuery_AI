/**
 * components/context/PairTypeDialog.tsx
 * =======================================
 * The pairing guardrail (DESIGN.md §4.1). Opens when an item is added to a
 * set that already has one, because that is the moment the set's TYPE is
 * decided and only the researcher knows which analysis they meant.
 *
 * Two rules make this dialog worth its interruption:
 *
 *  1. It offers only the pair types these two items can actually satisfy
 *     (api/pairOptions.ts), so no offer here can fail validation.
 *  2. It still LISTS every blocked option with the reason it's blocked.
 *     Silently hiding "bitemporal pair" leaves a researcher who came
 *     specifically to compare dates with no idea that the two captures they
 *     picked share a date. The reason is the useful part.
 *
 * "Replace the current item" is always available: sometimes the second
 * click was a correction, not an addition.
 */
import { useContextStore } from "../../state/useContextStore";
import { useToastStore } from "../../state/useToastStore";
import { describeItem, PAIR_TYPE_LABEL, type PairType } from "../../api/pairOptions";

const PAIR_ACTION: Record<PairType, { label: string; icon: string }> = {
  bitemporal_pair: { label: "Make a bitemporal pair", icon: "ph-clock-counter-clockwise" },
  cross_modal_pair: { label: "Make a cross-modal pair", icon: "ph-arrows-merge" },
};

export function PairTypeDialog() {
  const pairPrompt = useContextStore((s) => s.pairPrompt);
  const resolvePairAs = useContextStore((s) => s.resolvePairAs);
  const replaceWithCandidate = useContextStore((s) => s.replaceWithCandidate);
  const cancelPairPrompt = useContextStore((s) => s.cancelPairPrompt);
  const showToast = useToastStore((s) => s.show);

  if (!pairPrompt) return null;
  const { existing, candidate, options } = pairPrompt;

  return (
    <div className="dialog-backdrop z-[85]" role="dialog" aria-modal="true" aria-label="This set already has an item">
      <div className="dialog elev-lg">
        <h4 className="dialog-title">This set already has an item</h4>

        <p className="dialog-body m-0">
          Pairing “{describeItem(existing)}” with “{describeItem(candidate)}”. Only the pair types this combination can
          actually satisfy are offered.
        </p>

        <div className="flex flex-col items-start gap-[5.6px]">
          {options.allowed.map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => {
                const result = resolvePairAs(type);
                if (result.ok) showToast(`Built a ${PAIR_TYPE_LABEL[type]}`);
              }}
              className="btn btn-primary text-[13px]"
            >
              <i className={`ph ${PAIR_ACTION[type].icon} text-[13px]`} aria-hidden="true" />
              {PAIR_ACTION[type].label}
            </button>
          ))}

          <button
            type="button"
            onClick={() => {
              replaceWithCandidate();
              showToast("Replaced the item in this context set");
            }}
            className="btn btn-secondary text-[13px]"
          >
            <i className="ph ph-arrows-clockwise text-[13px]" aria-hidden="true" />
            Replace the current item
          </button>
        </div>

        {options.blocked.length > 0 && (
          <div className="flex flex-col gap-[5.6px]">
            {options.blocked.map((blocked) => (
              <p key={blocked.type} className="m-0 flex items-start gap-[6px] text-[11.5px] leading-[1.5] text-neutral-400">
                <i className="ph ph-prohibit mt-[2px] flex-none text-[12px] text-accent-400" aria-hidden="true" />
                {blocked.reason}
              </p>
            ))}
          </div>
        )}

        <div className="dialog-actions">
          <button type="button" onClick={cancelPairPrompt} className="btn btn-secondary text-[13px]">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
