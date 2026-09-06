/**
 * components/map/FreeDrawTool.tsx
 * =================================
 * The free-draw tool (DESIGN.md §2.4): click to place vertices,
 * double-click or press Enter to close the shape. Closing produces a
 * PENDING selection — never a context item directly. Confirming it is
 * PendingSelectionLayer's job.
 *
 * Which patches the shape covers is resolved CLIENT-side, with Turf, against
 * the footprints already in memory (lib/resolvePatchOverlap). There is no
 * network call for this: we know the geometry and we know the footprints,
 * so asking the server would only add latency to a number the researcher is
 * about to read. The count is reported before commit and sent with the item
 * as `patchCount` / `resolvedPatchIds`, but the UI never gates on it — a
 * shape spanning four patches is a legitimate thing to ask about.
 *
 * MapLibre's double-click zoom is disabled while this tool is active,
 * because the gesture that closes a shape would otherwise also zoom.
 */
import { useEffect } from "react";
import type maplibregl from "maplibre-gl";
import { useMapStore } from "../../state/useMapStore";
import { resolvePatchOverlap } from "../../lib/resolvePatchOverlap";
import { SHAPE_PAINT } from "../../styles/tokens";

const SOURCE_ID = "free-draw";
const LINE_LAYER_ID = "free-draw-line";
const VERTEX_LAYER_ID = "free-draw-vertices";
const MIN_VERTICES = 3;

interface FreeDrawToolProps {
  map: maplibregl.Map;
}

function inProgressGeoJson(vertices: [number, number][]): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = vertices.map((coordinates) => ({
    type: "Feature",
    properties: {},
    geometry: { type: "Point", coordinates },
  }));
  if (vertices.length >= 2) {
    features.push({
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: vertices },
    });
  }
  return { type: "FeatureCollection", features };
}

export function FreeDrawTool({ map }: FreeDrawToolProps) {
  const activeTool = useMapStore((s) => s.activeTool);
  const vertices = useMapStore((s) => s.freeDrawVertices);
  const addFreeDrawVertex = useMapStore((s) => s.addFreeDrawVertex);
  const resetFreeDraw = useMapStore((s) => s.resetFreeDraw);
  const setPendingSelection = useMapStore((s) => s.setPendingSelection);
  const footprints = useMapStore((s) => s.footprints);

  // --- Layers for the in-progress polyline --------------------------------
  useEffect(() => {
    if (map.getSource(SOURCE_ID)) return;
    map.addSource(SOURCE_ID, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: LINE_LAYER_ID,
      type: "line",
      source: SOURCE_ID,
      filter: ["==", ["geometry-type"], "LineString"],
      paint: {
        "line-color": SHAPE_PAINT.pending.line,
        "line-width": 1.75,
        // A shorter dash than a committed pending shape: this one is still
        // being drawn, and reads as a trail rather than an outline.
        "line-dasharray": [7, 5],
      },
    });
    map.addLayer({
      id: VERTEX_LAYER_ID,
      type: "circle",
      source: SOURCE_ID,
      filter: ["==", ["geometry-type"], "Point"],
      paint: { "circle-radius": 4, "circle-color": SHAPE_PAINT.pending.line },
    });
  }, [map]);

  // --- Keep the polyline in sync with the vertex list ---------------------
  useEffect(() => {
    const source = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    source?.setData(inProgressGeoJson(activeTool === "free_draw" ? vertices : []));
  }, [map, vertices, activeTool]);

  // --- Interactions, only while this tool is active -----------------------
  useEffect(() => {
    if (activeTool !== "free_draw") return;

    function closeShape() {
      const current = useMapStore.getState().freeDrawVertices;
      if (current.length < MIN_VERTICES) return;
      const ring: [number, number][] = [...current, current[0]];
      setPendingSelection({
        method: "free_draw",
        geometry: { type: "Polygon", coordinates: [ring] },
        resolvedPatchIds: resolvePatchOverlap(current, footprints),
      });
      resetFreeDraw();
    }

    function handleClick(event: maplibregl.MapMouseEvent) {
      addFreeDrawVertex([event.lngLat.lng, event.lngLat.lat]);
    }
    function handleDoubleClick(event: maplibregl.MapMouseEvent) {
      // The dblclick fires after its two clicks, so the vertex the second
      // click placed is already in the list — nothing to add, just close.
      event.preventDefault();
      closeShape();
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Enter") closeShape();
    }

    map.doubleClickZoom.disable();
    map.getCanvas().style.cursor = "crosshair";
    map.on("click", handleClick);
    map.on("dblclick", handleDoubleClick);
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      map.doubleClickZoom.enable();
      map.getCanvas().style.cursor = "";
      map.off("click", handleClick);
      map.off("dblclick", handleDoubleClick);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [map, activeTool, addFreeDrawVertex, resetFreeDraw, setPendingSelection, footprints]);

  return null;
}
