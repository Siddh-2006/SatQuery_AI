/**
 * components/context/ContextChip.tsx
 * ====================================
 * One item in the active context set (DESIGN.md §4.3).
 *
 * The thumbnail tile carries the icon of the METHOD that created the item —
 * footprint click, free draw, point segment, upload. How something entered
 * context is part of what it is: a hand-drawn area and an indexed patch
 * behave differently in pairing, and a researcher scanning the set needs to
 * see which is which without reading.
 *
 * Hovering sets the shared hover id, which lights up the matching shape on
 * the map (see useContextStore's hoveredContextItemId). Clicking a patch
 * chip opens the viewer, since the chip is the only handle on a patch once
 * the map has been panned away from it.
 *
 * A multi-patch area selection shows its patch count as a plain tag, not a
 * warning. Spanning several patches is legitimate — the count is sent with
 * the item and the UI never gates on it (§2.4).
 */
import { useMapStore } from "../../state/useMapStore";
import { useContextStore } from "../../state/useContextStore";
import type { ContextItem } from "../../api/types";

const METHOD_ICON: Record<string, string> = {
  patch: "ph-cursor",
  free_draw: "ph-pencil-simple",
  point_segment: "ph-map-pin",
  uploaded_image: "ph-upload-simple",
};

const BAND_LABEL: Record<string, string> = {
  default_rgb: "default RGB",
  sar_only: "SAR only",
  full_bands: "full S1+S2 bands",
};

function iconFor(item: ContextItem): string {
  if (item.kind === "patch") return METHOD_ICON.patch;
  if (item.kind === "uploaded_image") return METHOD_ICON.uploaded_image;
  return METHOD_ICON[item.method];
}

function titleFor(item: ContextItem): string {
  if (item.kind === "patch") return `${item.patchId} · ${item.timestamp}`;
  if (item.kind === "uploaded_image") return item.originalFilename;
  return item.method === "free_draw" ? "Free-draw area" : "Segmented mask";
}

function subtitleFor(item: ContextItem): string {
  if (item.kind === "patch") return BAND_LABEL[item.bandSelection] ?? item.bandSelection;
  if (item.kind === "uploaded_image") {
    return [item.format, item.detectedModality ?? "modality set manually", item.detectedTimestamp ?? "no date"].join(
      " · ",
    );
  }
  const method = item.method === "free_draw" ? "free draw" : "point segment";
  return item.segmentationConfidence !== undefined
    ? `${method} · mask confidence ${Math.round(item.segmentationConfidence * 100)}%`
    : method;
}

interface ContextChipProps {
  item: ContextItem;
  contextSetId: string;
  index: number;
}

export function ContextChip({ item, contextSetId, index }: ContextChipProps) {
  const removeItem = useContextStore((s) => s.removeItem);
  const hoveredContextItemId = useContextStore((s) => s.hoveredContextItemId);
  const setHoveredContextItemId = useContextStore((s) => s.setHoveredContextItemId);
  const setHoveredPatchId = useMapStore((s) => s.setHoveredPatchId);
  const openDrawerFor = useMapStore((s) => s.openDrawerFor);

  const chipId = `${contextSetId}:${index}`;
  const isHot = hoveredContextItemId === chipId;
  const patchCount = item.kind === "area_selection" ? item.resolvedPatchIds.length : 0;

  function handleEnter() {
    setHoveredContextItemId(chipId);
    // Patch items share their id namespace with the footprint layer, so the
    // map can highlight them directly. Area selections and uploads have no
    // footprint to light up — PendingSelectionLayer reads the chip id
    // instead.
    if (item.kind === "patch") setHoveredPatchId(item.patchId);
  }

  function handleLeave() {
    setHoveredContextItemId(null);
    setHoveredPatchId(null);
  }

  return (
    <div
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      className="flex items-center gap-[8.4px] rounded-sm bg-neutral-900 p-[5.6px]"
      style={isHot ? { background: "var(--color-accent-900)", boxShadow: "inset 0 0 0 1px var(--color-accent)" } : undefined}
    >
      <div
        role={item.kind === "patch" ? "button" : undefined}
        tabIndex={item.kind === "patch" ? 0 : undefined}
        onClick={item.kind === "patch" ? () => openDrawerFor(item.patchId) : undefined}
        onKeyDown={
          item.kind === "patch"
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") openDrawerFor(item.patchId);
              }
            : undefined
        }
        title={item.kind === "patch" ? "Open in patch viewer" : undefined}
        className={`flex h-[34px] w-[34px] flex-none items-center justify-center rounded-sm bg-neutral-900 text-[15px] text-accent-300 ${
          item.kind === "patch" ? "cursor-pointer" : ""
        }`}
      >
        <i className={`ph ${iconFor(item)}`} aria-hidden="true" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px]">{titleFor(item)}</div>
        <div className="truncate text-[11px] text-neutral-500">{subtitleFor(item)}</div>
      </div>

      {patchCount > 1 && <span className="tag tag-neutral flex-none">{patchCount} patches</span>}

      <button
        type="button"
        onClick={() => removeItem(contextSetId, index)}
        aria-label={`Remove ${titleFor(item)}`}
        className="btn-bare h-[24px] w-[24px] text-[13px]"
      >
        <i className="ph ph-x" />
      </button>
    </div>
  );
}
