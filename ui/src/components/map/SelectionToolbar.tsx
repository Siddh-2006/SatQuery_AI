/**
 * components/map/SelectionToolbar.tsx
 * =====================================
 * Picks which of the three selection tools a map click feeds (DESIGN.md
 * §2.2), and — the part that earns its space — states what a click will
 * actually DO under the current tool.
 *
 * The hint text is not decoration. All three tools respond to the same
 * gesture (a click on imagery) with completely different consequences, one
 * of which costs a network round-trip. Saying so beside the control is
 * cheaper than letting a researcher discover it by adding something they
 * didn't mean to.
 *
 * The active state is the design system's own `.seg-opt:has(input:checked)`
 * accent ring; it is not restyled here.
 */
import { useMapStore, type MapTool } from "../../state/useMapStore";

const TOOLS: { value: MapTool; label: string; icon: string; hint: string }[] = [
  {
    value: "none",
    label: "None",
    icon: "ph-hand",
    hint: "No tool active — pan and zoom freely; nothing is opened or added on click.",
  },
  {
    value: "footprint",
    label: "Footprint",
    icon: "ph-cursor",
    hint: "Click a footprint to open its popover — nothing is added on a single click.",
  },
  {
    value: "free_draw",
    label: "Free draw",
    icon: "ph-pencil-simple",
    hint: "Click to place vertices, double-click or press Enter to close the shape.",
  },
  {
    value: "point_segment",
    label: "Point segment",
    icon: "ph-map-pin",
    hint: "Click one point; POST /api/segment returns a mask to confirm or reject.",
  },
];

export function SelectionToolbar() {
  const activeTool = useMapStore((s) => s.activeTool);
  const setActiveTool = useMapStore((s) => s.setActiveTool);
  const showFootprints = useMapStore((s) => s.showFootprints);
  const toggleShowFootprints = useMapStore((s) => s.toggleShowFootprints);
  const hint = TOOLS.find((tool) => tool.value === activeTool)?.hint;

  return (
    <div className="relative z-20 flex flex-none items-center gap-[11.2px] px-[11.2px] py-[8.4px]">
      <div
        className="seg"
        style={{
          background: "color-mix(in srgb, var(--color-bg) 85%, transparent)",
          backdropFilter: "blur(6px)",
        }}
      >
        {TOOLS.map((tool) => (
          <label key={tool.value} className="seg-opt">
            <input
              type="radio"
              name="selection-tool"
              value={tool.value}
              checked={activeTool === tool.value}
              onChange={() => setActiveTool(tool.value)}
            />
            <i className={`ph ${tool.icon} text-[14px]`} aria-hidden="true" />
            {tool.label}
          </label>
        ))}
      </div>

      {/* Independent of the tool radios above: this only hides/shows the
          yellow footprint borders, it doesn't change what a click does —
          see MapTool vs showFootprints in useMapStore. */}
      <button
        type="button"
        onClick={toggleShowFootprints}
        aria-pressed={showFootprints}
        title={showFootprints ? "Hide patch footprints" : "Show patch footprints"}
        className="btn btn-secondary gap-[6px] px-[8px] py-[4px] text-[12px]"
      >
        <i className={`ph ${showFootprints ? "ph-eye" : "ph-eye-slash"} text-[14px]`} aria-hidden="true" />
        {showFootprints ? "Hide footprints" : "Show footprints"}
      </button>

      <p className="m-0 max-w-[340px] text-[11.5px] leading-[1.4] text-neutral-500">{hint}</p>
    </div>
  );
}
