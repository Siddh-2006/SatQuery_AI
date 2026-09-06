/**
 * components/map/PointSegmentTool.tsx
 * =====================================
 * The point-segment tool (DESIGN.md §2.5): one click sends
 * `POST /api/segment` with that point, and the mask that comes back becomes
 * a PENDING selection with its confidence attached.
 *
 * A returned mask is NEVER added automatically. It is a model's guess at
 * what the researcher meant by one click, its confidence is part of the
 * result, and the confirm bar shows both before anything enters context.
 *
 * `patchIdHint` is sent only when the click happened inside the patch
 * viewer, where we know which patch is on screen. From the map we don't
 * pretend to: the point is the only thing we actually know.
 *
 * A failed segmentation is shown here, on the map, next to where the click
 * happened — not as a toast. The researcher's next action is to click
 * somewhere else, so the message has to still be there when they do.
 */
import { useEffect, useState } from "react";
import type maplibregl from "maplibre-gl";
import { useMapStore } from "../../state/useMapStore";
import { postSegment } from "../../api/client";
import { ApiError } from "../../api/types";

interface PointSegmentToolProps {
  map: maplibregl.Map;
}

export function PointSegmentTool({ map }: PointSegmentToolProps) {
  const activeTool = useMapStore((s) => s.activeTool);
  const setPendingSelection = useMapStore((s) => s.setPendingSelection);
  const [isSegmenting, setIsSegmenting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTool !== "point_segment") {
      setError(null);
      return;
    }

    async function handleClick(event: maplibregl.MapMouseEvent) {
      setIsSegmenting(true);
      setError(null);
      try {
        const response = await postSegment({ point: { lat: event.lngLat.lat, lon: event.lngLat.lng } });
        setPendingSelection({
          method: "point_segment",
          geometry: response.geometry,
          resolvedPatchIds: response.resolvedPatchIds,
          confidence: response.confidence,
        });
      } catch (caught) {
        setError(
          caught instanceof ApiError ? caught.message : "Segmentation failed. Try a point inside a footprint.",
        );
      } finally {
        setIsSegmenting(false);
      }
    }

    map.getCanvas().style.cursor = "crosshair";
    map.on("click", handleClick);
    return () => {
      map.getCanvas().style.cursor = "";
      map.off("click", handleClick);
    };
  }, [map, activeTool, setPendingSelection]);

  if (activeTool !== "point_segment" || (!isSegmenting && !error)) return null;

  return (
    <div className="pointer-events-none absolute left-1/2 top-[11.2px] z-[30] -translate-x-1/2">
      {isSegmenting && (
        <div className="elev-md animate-sq-pulse rounded-md bg-surface px-[11.2px] py-[6px] text-[12px] text-neutral-300">
          POST /api/segment — waiting for a mask…
        </div>
      )}
      {!isSegmenting && error && (
        <p className="elev-md m-0 flex items-start gap-[6px] rounded-md bg-accent-900 px-[8px] py-[6px] text-[11.5px] text-accent-200">
          <i className="ph ph-warning-circle mt-[2px] text-[12px]" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}
