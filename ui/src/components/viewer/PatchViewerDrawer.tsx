/**
 * components/viewer/PatchViewerDrawer.tsx
 * =========================================
 * The patch viewer (DESIGN.md §2.6): a slide-over showing one patch's
 * preview, its grounding evidence, and its metadata.
 *
 * Anchored to the map FRAME rather than the window. It is a closer look at
 * what the map is showing, so it belongs inside the map's bounds — and
 * that way opening it never disturbs the context panel or the chat, which
 * the researcher is usually reading it against.
 *
 * Opening the viewer does not touch context. "Add to context" is an
 * explicit action here, the same as in the popover, so a patch can be
 * inspected and rejected without side effects.
 *
 * "Segment inside" switches the active tool to point-segment rather than
 * doing anything itself: the researcher still has to say WHERE, and a
 * segment request needs a point.
 *
 * The preview is a server-rendered composite; the gradient behind it is a
 * placeholder that shows through until that endpoint serves imagery. It
 * differs per composite so it can never be mistaken for the same picture
 * three times.
 */
import { useState } from "react";
import { useMapStore } from "../../state/useMapStore";
import { useContextStore } from "../../state/useContextStore";
import { useChatStore } from "../../state/useChatStore";
import { useToastStore } from "../../state/useToastStore";
import { BandCompositeSelector } from "./BandCompositeSelector";
import { MaskOverlay } from "../map/MaskOverlay";
import { COMPOSITE_PLACEHOLDER } from "../../styles/tokens";
import { patchPreviewUrl } from "../../api/client";
import type { PatchRef } from "../../api/types";

/** Fixed for now — the mock patches all carry both sensors and the same
 *  band list. Replace with per-patch values as soon as the API returns
 *  them; the rows exist so the shape of the answer is visible. */
const SENSOR_LABEL = "Sentinel-2 MSI · Sentinel-1 C-SAR";
const BAND_LABEL = "B01–B12, VV, VH";

export function PatchViewerDrawer() {
  const drawerOpen = useMapStore((s) => s.drawerOpen);
  const activePatchId = useMapStore((s) => s.activePatchId);
  const closeDrawer = useMapStore((s) => s.closeDrawer);
  const composite = useMapStore((s) => s.composite);
  const resolution = useMapStore((s) => s.resolution);
  const footprints = useMapStore((s) => s.footprints);
  const setActiveTool = useMapStore((s) => s.setActiveTool);
  const addItemToActiveSet = useContextStore((s) => s.addItemToActiveSet);
  const messages = useChatStore((s) => s.messages);
  const hoveredEvidenceId = useChatStore((s) => s.hoveredEvidenceId);
  const showToast = useToastStore((s) => s.show);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const feature = footprints?.features.find((f) => f.properties.patchId === activePatchId);
  if (!drawerOpen || !feature) return null;

  const { patchId, label, lat, lon, availableModalities, availableTimestamps } = feature.properties;
  const timestamp = availableTimestamps[availableTimestamps.length - 1];

  // Grounding for THIS patch, from the most recent answer that produced
  // any — older answers' overlays would be misleading next to a newer one.
  const evidence =
    [...messages]
      .reverse()
      .find((message) => message.evidence?.some((item) => item.patchId === patchId))
      ?.evidence?.filter((item) => item.patchId === patchId) ?? [];

  function handleAdd() {
    const item: PatchRef = {
      kind: "patch",
      patchId,
      lat,
      lon,
      timestamp,
      availableModalities,
      bandSelection: "default_rgb",
    };
    const result = addItemToActiveSet(item);
    if (result.ok) {
      setError(null);
      showToast(`${patchId} added to context`);
    } else if (result.needsPairChoice) {
      setError(null);
    } else {
      setError(result.reason ?? null);
    }
  }

  return (
    <aside className="elev-lg absolute bottom-0 right-0 top-0 z-[35] flex w-[min(330px,72%)] flex-col gap-[11.2px] overflow-y-auto bg-surface p-[11.2px]">
      <div className="flex items-start gap-[8.4px]">
        <div className="min-w-0 flex-1">
          <span className="card-kicker">Patch viewer</span>
          <h3 className="font-heading text-[17px] font-medium">{patchId}</h3>
        </div>
        <button type="button" onClick={closeDrawer} aria-label="Close patch viewer" className="btn-bare h-[24px] w-[24px] text-[14px]">
          <i className="ph ph-x" />
        </button>
      </div>

      <BandCompositeSelector />

      <div
        className="relative aspect-square w-full overflow-hidden rounded-sm"
        style={{ background: COMPOSITE_PLACEHOLDER[composite] }}
      >
        {!previewFailed && (
          <img
            src={patchPreviewUrl(patchId, composite)}
            alt={`${patchId} — ${composite.replace("_", " ")} composite`}
            className="h-full w-full object-cover"
            onError={() => setPreviewFailed(true)}
          />
        )}
        {evidence.map((item) => (
          <MaskOverlay
            key={item.id}
            id={item.id}
            kind={item.kind}
            geometry={item.geometry}
            label={item.label}
            hot={hoveredEvidenceId === item.id}
          />
        ))}
        {/* The evidence label only appears while its span is hovered —
            permanent labels would compete with the imagery they annotate. */}
        {hoveredEvidenceId && (
          <span className="pointer-events-none absolute bottom-[6px] left-[6px] rounded-sm bg-[rgba(0,0,0,.6)] px-[6px] py-[2px] text-[11px] text-accent-200">
            {evidence.find((item) => item.id === hoveredEvidenceId)?.label}
          </span>
        )}
      </div>

      <table className="table text-[12.5px]">
        <tbody>
          <tr>
            <th className="w-[96px]">Location</th>
            <td>{label}</td>
          </tr>
          <tr>
            <th>Lat / lon</th>
            <td className="tabular-nums">
              {lat.toFixed(4)} / {lon.toFixed(4)}
            </td>
          </tr>
          <tr>
            <th>Captured</th>
            <td className="tabular-nums">{timestamp}</td>
          </tr>
          <tr>
            <th>Sensor</th>
            <td>{SENSOR_LABEL}</td>
          </tr>
          <tr>
            <th>Resolution</th>
            <td>{resolution}</td>
          </tr>
          <tr>
            <th>Bands</th>
            <td>{BAND_LABEL}</td>
          </tr>
        </tbody>
      </table>

      {error && (
        <p className="m-0 flex items-start gap-[6px] rounded-sm bg-accent-900 px-[8px] py-[6px] text-[11.5px] leading-[1.45] text-accent-200">
          <i className="ph ph-warning-circle mt-[2px] text-[12px]" aria-hidden="true" />
          {error}
        </p>
      )}

      <div className="flex flex-col items-start gap-[5.6px]">
        <button type="button" onClick={handleAdd} className="btn btn-primary text-[12.5px]">
          Add to context
        </button>
        <button
          type="button"
          onClick={() => setActiveTool("point_segment")}
          className="btn btn-secondary text-[12.5px]"
        >
          Segment inside
        </button>
      </div>

      <p className="m-0 text-[11px] leading-[1.45] text-neutral-600">
        Composites are rendered server-side — GET /api/patches/{patchId}/preview?composite={composite}. Nothing here
        decodes raster data in the browser.
      </p>
    </aside>
  );
}
