/**
 * components/map/PatchPopover.tsx
 * =================================
 * What a footprint click opens (DESIGN.md §2.3). A single click never adds
 * anything — it opens this, and the researcher picks HOW the patch enters
 * context. That is the whole reason the popover exists: band selection is a
 * real narrowing of what the orchestrator receives (`sar_only` genuinely
 * removes the optical bands from the request), so it has to be a decision,
 * not a default applied behind the researcher's back.
 *
 * "Inspect" opens the viewer drawer without touching context, so a patch
 * can be examined before committing to it.
 *
 * Positioned by projecting the patch's own centre through map.project, so
 * it tracks the footprint while the map pans; MapView re-renders this on
 * every "move". Clamped inside the map frame so a patch near an edge can't
 * push it out of view.
 */
import { useState } from "react";
import type maplibregl from "maplibre-gl";
import { useMapStore } from "../../state/useMapStore";
import { useContextStore } from "../../state/useContextStore";
import { useToastStore } from "../../state/useToastStore";
import type { BandSelection, PatchRef } from "../../api/types";

const POPOVER_WIDTH = 236;
const OFFSET_X = 14;
const OFFSET_Y = -10;

const BAND_ACTIONS: { bandSelection: BandSelection; label: string; primary: boolean }[] = [
  { bandSelection: "default_rgb", label: "Add (default RGB)", primary: true },
  { bandSelection: "sar_only", label: "Add SAR only", primary: false },
  { bandSelection: "full_bands", label: "Add full S1+S2 bands", primary: false },
];

const MODALITY_LABEL: Record<string, string> = { optical: "S2 (optical)", sar: "S1 (SAR)" };

interface PatchPopoverProps {
  map: maplibregl.Map;
}

export function PatchPopover({ map }: PatchPopoverProps) {
  const popoverOpen = useMapStore((s) => s.popoverOpen);
  const activePatchId = useMapStore((s) => s.activePatchId);
  const closePopover = useMapStore((s) => s.closePopover);
  const openDrawerFor = useMapStore((s) => s.openDrawerFor);
  const setTemporalPatchId = useMapStore((s) => s.setTemporalPatchId);
  const footprints = useMapStore((s) => s.footprints);
  const addItemToActiveSet = useContextStore((s) => s.addItemToActiveSet);
  const showToast = useToastStore((s) => s.show);
  const [error, setError] = useState<string | null>(null);

  const feature = footprints?.features.find((f) => f.properties.patchId === activePatchId);
  if (!popoverOpen || !feature) return null;

  const { patchId, label, lat, lon, availableModalities, availableTimestamps } = feature.properties;

  // The most recent capture is the default. Any other date is chosen
  // deliberately, through the temporal browser (§4.4) — which is also the
  // only way to build a bitemporal pair, so there's no second guess to make
  // here.
  const timestamp = availableTimestamps[availableTimestamps.length - 1];

  const point = map.project([lon, lat]);
  const frameWidth = map.getContainer().clientWidth;
  const left = Math.min(Math.max(point.x + OFFSET_X, 8), Math.max(frameWidth - POPOVER_WIDTH - 8, 8));
  const top = Math.max(point.y + OFFSET_Y, 8);

  function handleAdd(bandSelection: BandSelection) {
    const item: PatchRef = {
      kind: "patch",
      patchId,
      lat,
      lon,
      timestamp,
      availableModalities,
      bandSelection,
    };
    const result = addItemToActiveSet(item);
    if (result.ok) {
      setError(null);
      closePopover();
      showToast(`${patchId} added to context`);
      return;
    }
    // needsPairChoice means the guardrail dialog has taken over — say
    // nothing and let it drive.
    if (result.needsPairChoice) {
      setError(null);
      closePopover();
      return;
    }
    setError(result.reason ?? null);
  }

  function handleOpenTemporal() {
    setTemporalPatchId(patchId);
    closePopover();
    showToast(`${patchId} — showing ${availableTimestamps.length} capture(s) in the temporal browser`);
  }

  return (
    <div
      className="card elev-md absolute z-[32] gap-[8.4px] p-[11.2px]"
      style={{ left, top, width: POPOVER_WIDTH }}
    >
      <div className="flex items-start gap-[8.4px]">
        <div className="min-w-0 flex-1">
          <h4 className="font-heading text-[15px] font-medium">Patch {patchId}</h4>
          <p className="m-0 text-[12px] text-neutral-400">{label}</p>
        </div>
        <button type="button" onClick={closePopover} aria-label="Close" className="btn-bare h-[22px] w-[22px] text-[13px]">
          <i className="ph ph-x" />
        </button>
      </div>

      <div className="text-[12px] leading-[1.5] text-neutral-400">
        <div>Captured: {timestamp}</div>
        <div>Available: {availableModalities.map((m) => MODALITY_LABEL[m] ?? m).join(", ")}</div>
      </div>

      <div className="flex flex-col items-start gap-[5.6px]">
        {BAND_ACTIONS.map((action) => (
          <button
            key={action.bandSelection}
            type="button"
            onClick={() => handleAdd(action.bandSelection)}
            className={`btn ${action.primary ? "btn-primary" : "btn-secondary"} text-[12.5px]`}
          >
            {action.label}
          </button>
        ))}
        <button
          type="button"
          onClick={handleOpenTemporal}
          disabled={availableTimestamps.length <= 1}
          title={
            availableTimestamps.length <= 1
              ? "Only one capture is known at this location"
              : `Browse all ${availableTimestamps.length} captures at this location`
          }
          className="btn btn-ghost text-[12.5px]"
        >
          <i className="ph ph-clock-counter-clockwise text-[12px]" aria-hidden="true" />
          Add to temporal explorer
        </button>
        <button
          type="button"
          onClick={() => openDrawerFor(patchId)}
          className="btn btn-ghost text-[12.5px]"
        >
          Inspect
          <i className="ph ph-caret-right text-[11px]" aria-hidden="true" />
        </button>
      </div>

      {error && (
        <p className="m-0 flex items-start gap-[6px] rounded-sm bg-accent-900 px-[8px] py-[6px] text-[11.5px] leading-[1.45] text-accent-200">
          <i className="ph ph-warning-circle mt-[2px] text-[12px]" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}
