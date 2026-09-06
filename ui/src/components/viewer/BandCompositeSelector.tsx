/**
 * components/viewer/BandCompositeSelector.tsx
 * =============================================
 * Picks which band composite the patch viewer requests (DESIGN.md §2.6):
 * true colour, false colour, or SAR.
 *
 * This is a VIEW control, not a context one. Changing it changes the image
 * the researcher is looking at; it does not change what the orchestrator
 * receives — that's the popover's band selection (§2.3). Keeping the two
 * apart is deliberate: conflating "what I'm looking at" with "what the
 * model gets" is how a researcher ends up sending SAR to a model they
 * thought was reading optical.
 *
 * Composites are rendered SERVER-side; this only selects a query
 * parameter.
 */
import { useMapStore, type BandComposite } from "../../state/useMapStore";

const COMPOSITES: { value: BandComposite; label: string }[] = [
  { value: "true_color", label: "True color" },
  { value: "false_color", label: "False color" },
  { value: "sar", label: "SAR" },
];

export function BandCompositeSelector() {
  const composite = useMapStore((s) => s.composite);
  const setComposite = useMapStore((s) => s.setComposite);

  return (
    <div className="seg self-start">
      {COMPOSITES.map((option) => (
        <label key={option.value} className="seg-opt text-[11.5px]">
          <input
            type="radio"
            name="band-composite"
            value={option.value}
            checked={composite === option.value}
            onChange={() => setComposite(option.value)}
          />
          {option.label}
        </label>
      ))}
    </div>
  );
}
