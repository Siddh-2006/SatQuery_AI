/**
 * components/map/MaskOverlay.tsx
 * =================================
 * Renders one piece of PIXEL-space evidence (a GroundingEvidence's
 * bbox/mask/point, DESIGN.md §6.1) over a patch preview image. Used by the
 * patch viewer to show an answer's grounding, and reusable for a pending
 * mask preview — the same visual language for "a model outlined this",
 * whether it's an output (grounding) or an input (a selection), per §4.3.
 *
 * MUST be rendered inside a `position: relative` container that exactly
 * wraps the preview it sits on: it positions itself in percentages, so it
 * scales with the image at any rendered size.
 *
 * Coordinate spaces do not mix here. This component understands a patch's
 * own raster coordinates ONLY. Geographic shapes — footprints, the
 * free-draw polygon — are a different space entirely and are drawn as
 * MapLibre layers, never through this component.
 *
 * Paint follows the evidence rows of the SHAPE_PAINT table: the hovered
 * variant is driven by the span the researcher is pointing at, which is
 * what makes the chat-to-image link legible in both directions.
 */
import { bboxToPercentRect, pointToPercent } from "../../lib/patchGeometry";
import { SHAPE_PAINT } from "../../styles/tokens";

interface MaskOverlayProps {
  /** Used as the React key upstream and to match the hovered evidence id. */
  id: string;
  kind: "bbox" | "mask" | "point";
  /** bbox: [xMin,yMin,xMax,yMax]; mask: an image URL; point: [x,y]. */
  geometry: number[] | string;
  label?: string;
  /** True while this evidence's grounded span is hovered. */
  hot?: boolean;
  /** Dashed = pending, not yet confirmed (§2.2). Never on committed
   *  evidence. */
  dashed?: boolean;
}

export function MaskOverlay({ id, kind, geometry, label, hot = false, dashed = false }: MaskOverlayProps) {
  const paint = hot ? SHAPE_PAINT.evidenceHot : SHAPE_PAINT.evidence;

  if (kind === "mask" && typeof geometry === "string") {
    // There is no per-pixel alignment metadata for a mask beyond "aligned
    // to the patch preview" (§6.1), so it covers the whole image — which is
    // what the backend renders it to match.
    return (
      <img
        src={geometry}
        alt={label ?? "segmentation mask"}
        title={label}
        className="pointer-events-none absolute inset-0 h-full w-full"
        style={{ opacity: hot ? 0.7 : 0.5, mixBlendMode: "screen" }}
      />
    );
  }

  if (kind === "bbox" && Array.isArray(geometry) && geometry.length === 4) {
    const rect = bboxToPercentRect(geometry as [number, number, number, number]);
    return (
      <div
        title={label}
        data-evidence-id={id}
        className="pointer-events-none absolute rounded-[2px]"
        style={{
          left: `${rect.leftPct}%`,
          top: `${rect.topPct}%`,
          width: `${rect.widthPct}%`,
          height: `${rect.heightPct}%`,
          border: `${paint.lineWidth + 0.5}px ${dashed ? "dashed" : "solid"} ${paint.line}`,
          background: paint.fill,
        }}
      />
    );
  }

  if (kind === "point" && Array.isArray(geometry) && geometry.length === 2) {
    const { leftPct, topPct } = pointToPercent(geometry as [number, number]);
    return (
      <div
        title={label}
        data-evidence-id={id}
        className="pointer-events-none absolute h-[10px] w-[10px] -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ left: `${leftPct}%`, top: `${topPct}%`, background: paint.line }}
      />
    );
  }

  // Malformed geometry for the given kind — render nothing rather than
  // throwing: one bad evidence item shouldn't blank the whole viewer.
  return null;
}
