/**
 * components/map/PendingSelectionLayer.tsx
 * ==========================================
 * Two things that belong together: the DASHED outline of whatever a tool
 * is currently holding unconfirmed, and the bar that confirms or cancels
 * it (DESIGN.md §2.2). It also draws the SOLID outlines of area selections
 * already committed to a context set, so both live in one layer and can't
 * disagree about geometry handling.
 *
 * The dash is the single visual signal for "this is not in context yet".
 * It is reused verbatim by the confirm bar's tile and by the upload
 * dialog's pending card, and it is the only thing distinguishing a shape
 * the researcher is about to add from one they already added. Nothing
 * committed is ever dashed.
 *
 * Confirming is where a UI-only PendingAreaSelection becomes a typed
 * AreaSelectionRef — see useMapStore's PendingAreaSelection for why the
 * two are separate shapes.
 */
import { useEffect } from "react";
import type maplibregl from "maplibre-gl";
import { useMapStore } from "../../state/useMapStore";
import { useContextStore } from "../../state/useContextStore";
import { useToastStore } from "../../state/useToastStore";
import { SHAPE_PAINT } from "../../styles/tokens";
import type { AreaSelectionRef } from "../../api/types";

const SOURCE_ID = "selections";
const FILL_LAYER_ID = "selections-fill";
const LINE_LAYER_ID = "selections-line";

interface PendingSelectionLayerProps {
  map: maplibregl.Map;
}

const METHOD_ICON: Record<AreaSelectionRef["method"], string> = {
  free_draw: "ph-pencil-simple",
  point_segment: "ph-map-pin",
};

export function PendingSelectionLayer({ map }: PendingSelectionLayerProps) {
  const pendingSelection = useMapStore((s) => s.pendingSelection);
  const clearPendingSelection = useMapStore((s) => s.clearPendingSelection);
  const contextSets = useContextStore((s) => s.contextSets);
  const activeContextSetId = useContextStore((s) => s.activeContextSetId);
  const hoveredContextItemId = useContextStore((s) => s.hoveredContextItemId);
  const addItemToActiveSet = useContextStore((s) => s.addItemToActiveSet);
  const showToast = useToastStore((s) => s.show);

  // Committed area selections across every context set, tagged so the line
  // layer can pick the "hot" paint for whichever chip is being hovered.
  const committed = contextSets.flatMap((contextSet) =>
    contextSet.items
      .map((item, index) => ({ item, id: `${contextSet.id}:${index}` }))
      .filter((entry) => entry.item.kind === "area_selection"),
  );

  useEffect(() => {
    if (map.getSource(SOURCE_ID)) return;
    map.addSource(SOURCE_ID, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: FILL_LAYER_ID,
      type: "fill",
      source: SOURCE_ID,
      paint: {
        "fill-color": ["case", ["get", "pending"], SHAPE_PAINT.pending.line, SHAPE_PAINT.areaSelection.line],
        "fill-opacity": ["case", ["get", "pending"], 0.14, ["get", "hot"], 0.28, 0.14],
      },
    });
    map.addLayer({
      id: LINE_LAYER_ID,
      type: "line",
      source: SOURCE_ID,
      paint: {
        "line-color": ["case", ["get", "pending"], SHAPE_PAINT.pending.line, SHAPE_PAINT.areaSelection.line],
        "line-width": [
          "case",
          ["get", "pending"],
          SHAPE_PAINT.pending.lineWidth,
          ["get", "hot"],
          SHAPE_PAINT.areaSelectionHot.lineWidth,
          SHAPE_PAINT.areaSelection.lineWidth,
        ],
        // MapLibre can't vary a dasharray per feature, so the pending shape
        // gets its own layer-level dash and committed shapes are drawn
        // solid — which is exactly the distinction being made anyway.
        "line-dasharray": ["literal", SHAPE_PAINT.pending.dash ?? [8, 5]],
      },
    });
    // A second, solid line layer for committed shapes, since the dash above
    // is a layer property rather than a per-feature one.
    map.addLayer({
      id: `${LINE_LAYER_ID}-solid`,
      type: "line",
      source: SOURCE_ID,
      filter: ["!", ["get", "pending"]],
      paint: {
        "line-color": SHAPE_PAINT.areaSelection.line,
        "line-width": [
          "case",
          ["get", "hot"],
          SHAPE_PAINT.areaSelectionHot.lineWidth,
          SHAPE_PAINT.areaSelection.lineWidth,
        ],
      },
    });
  }, [map]);

  useEffect(() => {
    const source = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (!source) return;

    const features: GeoJSON.Feature[] = committed.map((entry) => {
      const item = entry.item as AreaSelectionRef;
      return {
        type: "Feature",
        properties: { pending: false, hot: hoveredContextItemId === entry.id },
        geometry: item.geometry,
      };
    });

    if (pendingSelection) {
      features.push({
        type: "Feature",
        properties: { pending: true, hot: false },
        geometry: pendingSelection.geometry,
      });
    }

    source.setData({ type: "FeatureCollection", features });
    // committed is rebuilt every render; key on its identity string instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, pendingSelection, hoveredContextItemId, committed.map((c) => c.id).join(",")]);

  if (!pendingSelection) return null;

  const patchCount = pendingSelection.resolvedPatchIds.length;
  const isSegment = pendingSelection.method === "point_segment";

  function handleAdd() {
    if (!pendingSelection) return;
    const item: AreaSelectionRef = {
      kind: "area_selection",
      method: pendingSelection.method,
      geometry: pendingSelection.geometry,
      resolvedPatchIds: pendingSelection.resolvedPatchIds,
      patchCount,
      ...(pendingSelection.confidence !== undefined
        ? { segmentationConfidence: pendingSelection.confidence }
        : {}),
    };
    const result = addItemToActiveSet(item);
    clearPendingSelection();
    if (result.ok) showToast(`Area added to ${activeContextSetId ?? "context"}`);
  }

  return (
    <div className="elev-md absolute bottom-[34px] left-1/2 z-[30] flex -translate-x-1/2 items-center gap-[11.2px] rounded-md bg-surface px-[11.2px] py-[8.4px]">
      <div
        className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-sm text-[13px] text-accent-300"
        style={{ border: "1px dashed var(--color-accent-300)" }}
        aria-hidden="true"
      >
        <i className={`ph ${METHOD_ICON[pendingSelection.method]}`} />
      </div>

      <div className="min-w-0">
        <div className="text-[13px]">{isSegment ? "Segmentation mask · SAM" : "Free-draw shape"}</div>
        <div className="text-[11.5px] text-neutral-500">
          overlaps {patchCount} {patchCount === 1 ? "patch" : "patches"}
          {isSegment && pendingSelection.confidence !== undefined
            ? ` · mask confidence ${Math.round(pendingSelection.confidence * 100)}%`
            : ""}
        </div>
      </div>

      <button type="button" onClick={handleAdd} className="btn btn-primary text-[12.5px]">
        Add to context
      </button>
      <button type="button" onClick={clearPendingSelection} className="btn btn-secondary text-[12.5px]">
        Cancel
      </button>
    </div>
  );
}
