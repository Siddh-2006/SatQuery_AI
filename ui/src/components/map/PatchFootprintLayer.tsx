/**
 * components/map/PatchFootprintLayer.tsx
 * =========================================
 * The footprint overlay from DESIGN.md §2.1: a border per indexed patch,
 * over the basemap, clickable to open its popover and hoverable for a
 * quick-details tooltip.
 *
 * Deliberately NOT a MapLibre GeoJSON source/layer. maplibre-gl 4.7.1 (the
 * version this app is pinned to) never resolves `map.on("idle")` and
 * renders zero features on a GeoJSON source whenever any feature carries an
 * `id`/`promoteId` — a real upstream bug (`promoteId` not passed to the
 * GeoJSON worker) only fixed in 5.21.1+. This layer needs per-patch
 * `feature-state` (hovered / inContext) to work at all, which requires an
 * id, so upgrading maplibre-gl was the only way to keep the GeoJSON-layer
 * approach — instead, this draws the footprints itself:
 *
 *  - A plain `<canvas>`, `pointer-events: none`, redrawn on every map
 *    "move"/"resize" by projecting each patch's real WGS84 polygon corners
 *    (lib/patchGeometry's source data, already the true footprint — not a
 *    fixed-size square) through `map.project()` and stroking the path.
 *  - Hit-testing (hover + click) is done ourselves with Turf's
 *    `booleanPointInPolygon` against `event.lngLat`, attached directly to
 *    the map — the same mechanism FreeDrawTool/PointSegmentTool already use
 *    for their own interactions, just applied to patches instead of a
 *    drawn shape.
 *
 * This is more code than `source.setData()` + a style object, but it only
 * depends on `map.project()`/`map.on()`, both plain synchronous APIs
 * untouched by the worker bug — so it works today, on the pinned version,
 * with no dependency change.
 *
 * Two independent ways this layer backs off, both driven by useMapStore:
 *  - `showFootprints: false` (SelectionToolbar's "Hide footprints" toggle)
 *    stops drawing entirely — for seeing the bare basemap under a dense
 *    patch grid.
 *  - `activeTool: "none"` stops hit-testing (hover tooltip, click popover)
 *    while leaving the borders visible — for panning/zooming a
 *    patch-covered area without a click on every attempt opening a
 *    popover, exactly like switching away from "free_draw"/"point_segment"
 *    already stops THEIR click handling.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type maplibregl from "maplibre-gl";
import { booleanPointInPolygon, point as turfPoint } from "@turf/turf";
import { useMapStore } from "../../state/useMapStore";
import { useContextStore } from "../../state/useContextStore";
import type { Modality, PatchFeatureCollection } from "../../api/types";

const BORDER = "#f4c430"; // yellow — deliberately not the SHAPE_PAINT purple ramp,
const BORDER_HOVER = "#ffe680"; // so this stands out as "here is where the data is"
const FILL_HOVER = "rgba(244,196,48,0.16)"; // rather than blending into the design system's
const FILL_IN_CONTEXT = "rgba(244,196,48,0.28)"; // usual footprint styling.
const LINE_WIDTH = 1.5;
const LINE_WIDTH_HOVER = 2.25;

const MODALITY_LABEL: Record<Modality, string> = { optical: "S2 (optical)", sar: "S1 (SAR)" };

interface PatchFootprintLayerProps {
  map: maplibregl.Map;
}

interface IndexedPatch {
  patchId: string;
  ring: [number, number][]; // [lon, lat] pairs, closed
  bbox: [number, number, number, number]; // minLon, minLat, maxLon, maxLat
}

function indexPatches(footprints: PatchFeatureCollection | null): IndexedPatch[] {
  if (!footprints) return [];
  return footprints.features.map((f) => {
    const ring = f.geometry.coordinates[0] as [number, number][];
    const lons = ring.map((p) => p[0]);
    const lats = ring.map((p) => p[1]);
    return {
      patchId: f.properties.patchId,
      ring,
      bbox: [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)],
    };
  });
}

export function PatchFootprintLayer({ map }: PatchFootprintLayerProps) {
  const footprints = useMapStore((s) => s.footprints);
  const hoveredPatchId = useMapStore((s) => s.hoveredPatchId);
  const setHoveredPatchId = useMapStore((s) => s.setHoveredPatchId);
  const openPopoverFor = useMapStore((s) => s.openPopoverFor);
  const activeTool = useMapStore((s) => s.activeTool);
  const showFootprints = useMapStore((s) => s.showFootprints);
  const contextSets = useContextStore((s) => s.contextSets);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Screen position (map-container-relative) of the tooltip, while hovering
  // a patch — null hides it. Separate from `hoveredPatchId` because the
  // tooltip also needs to track cursor position, not just which patch.
  const [tooltip, setTooltip] = useState<{ x: number; y: number; patchId: string } | null>(null);

  // Every patchId in ANY context set, not just the active one — a footprint
  // already used somewhere reads differently so the researcher can see at a
  // glance what they've already pulled in.
  const contextPatchIds = new Set(
    contextSets.flatMap((contextSet) =>
      contextSet.items.filter((item) => item.kind === "patch").map((item) => item.patchId),
    ),
  );
  const contextPatchIdsKey = [...contextPatchIds].sort().join(",");

  const indexed = useMemo(() => indexPatches(footprints), [footprints]);

  // --- Draw: yellow border per patch, redrawn as the map moves ------------
  useEffect(() => {
    function draw() {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const container = map.getContainer();
      const { width, height } = container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      if (!showFootprints) return; // hidden — leave the canvas blank

      const bounds = map.getBounds();
      const viewMinLon = bounds.getWest();
      const viewMinLat = bounds.getSouth();
      const viewMaxLon = bounds.getEast();
      const viewMaxLat = bounds.getNorth();

      for (const patch of indexed) {
        const [minLon, minLat, maxLon, maxLat] = patch.bbox;
        // Cheap cull: skip anything whose bbox can't possibly intersect the
        // current viewport before paying for five map.project() calls.
        if (maxLon < viewMinLon || minLon > viewMaxLon || maxLat < viewMinLat || minLat > viewMaxLat) continue;

        const screen = patch.ring.map(([lon, lat]) => map.project([lon, lat]));
        const isHovered = patch.patchId === hoveredPatchId;
        const isInContext = contextPatchIds.has(patch.patchId);

        ctx.beginPath();
        screen.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
        ctx.closePath();
        if (isInContext) {
          ctx.fillStyle = FILL_IN_CONTEXT;
          ctx.fill();
        } else if (isHovered) {
          ctx.fillStyle = FILL_HOVER;
          ctx.fill();
        }
        ctx.strokeStyle = isHovered ? BORDER_HOVER : BORDER;
        ctx.lineWidth = isHovered ? LINE_WIDTH_HOVER : LINE_WIDTH;
        ctx.stroke();
      }
    }

    draw();
    map.on("move", draw);
    map.on("resize", draw);
    // Layout changes (side panel collapse, drawer open) resize the map
    // container without moving or resizing the map itself.
    const resizeObserver = new ResizeObserver(draw);
    resizeObserver.observe(map.getContainer());

    return () => {
      map.off("move", draw);
      map.off("resize", draw);
      resizeObserver.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- contextPatchIds
    // is a fresh Set every render by construction; keyed on its contents.
  }, [map, indexed, hoveredPatchId, contextPatchIdsKey, showFootprints]);

  // --- Hit-testing: hover shows a tooltip, click opens the popover --------
  // Only while "footprint" is the active tool (matching every other map
  // tool's gating, §2.2 — otherwise a free-draw click would also resolve to
  // a patch underneath it) and while footprints are actually visible —
  // hovering/clicking something you can't see would be confusing, and this
  // is also the "None" tool's entire point (see header comment).
  useEffect(() => {
    if (activeTool !== "footprint" || !showFootprints) return;

    function patchAt(lngLat: maplibregl.LngLat): IndexedPatch | null {
      const { lng, lat } = lngLat;
      const candidates = indexed.filter(
        (p) => lng >= p.bbox[0] && lng <= p.bbox[2] && lat >= p.bbox[1] && lat <= p.bbox[3],
      );
      if (candidates.length === 0) return null;
      const pt = turfPoint([lng, lat]);
      return candidates.find((p) => booleanPointInPolygon(pt, { type: "Polygon", coordinates: [p.ring] })) ?? null;
    }

    function handleMouseMove(event: maplibregl.MapMouseEvent) {
      const hit = patchAt(event.lngLat);
      setHoveredPatchId(hit?.patchId ?? null);
      setTooltip(hit ? { x: event.point.x, y: event.point.y, patchId: hit.patchId } : null);
      map.getCanvas().style.cursor = hit ? "pointer" : "";
    }
    function handleClick(event: maplibregl.MapMouseEvent) {
      const hit = patchAt(event.lngLat);
      if (hit) openPopoverFor(hit.patchId);
    }
    function handleMouseLeave() {
      setHoveredPatchId(null);
      setTooltip(null);
      map.getCanvas().style.cursor = "";
    }

    map.on("mousemove", handleMouseMove);
    map.on("click", handleClick);
    map.on("mouseout", handleMouseLeave);

    return () => {
      map.off("mousemove", handleMouseMove);
      map.off("click", handleClick);
      map.off("mouseout", handleMouseLeave);
      setHoveredPatchId(null);
      setTooltip(null);
      map.getCanvas().style.cursor = "";
    };
  }, [map, activeTool, showFootprints, indexed, openPopoverFor, setHoveredPatchId]);

  const tooltipFeature = tooltip && footprints?.features.find((f) => f.properties.patchId === tooltip.patchId);

  return (
    <>
      <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 z-[20]" />
      {tooltip && tooltipFeature && (
        <div
          className="card pointer-events-none absolute z-[31] gap-[4px] p-[8px] text-[11.5px] leading-[1.5]"
          style={{ left: tooltip.x + 14, top: tooltip.y + 14, maxWidth: 220 }}
        >
          <div className="font-heading text-[12.5px] font-medium">{tooltipFeature.properties.patchId}</div>
          <div className="text-neutral-400">{tooltipFeature.properties.label}</div>
          <div className="text-neutral-400">
            {tooltipFeature.properties.availableModalities.map((m) => MODALITY_LABEL[m] ?? m).join(" · ")}
          </div>
          <div className="text-neutral-400">Captures: {tooltipFeature.properties.availableTimestamps.join(", ")}</div>
          <div className="text-neutral-600">
            {tooltipFeature.properties.lat.toFixed(4)}, {tooltipFeature.properties.lon.toFixed(4)}
          </div>
        </div>
      )}
    </>
  );
}
