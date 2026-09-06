/**
 * lib/patchGeometry.ts
 * ======================
 * Grounding evidence (bbox/point kinds) comes back in a patch's PIXEL
 * space (DESIGN.md §6.1's GroundingEvidence.geometry comment), not
 * lng/lat — because the orchestrator is reasoning over the actual raster,
 * not a map projection. To draw that evidence on top of a patch's preview
 * image (in PatchViewerDrawer / MaskOverlay), we need to know the pixel
 * dimensions of that raster to convert a pixel box into a CSS percentage
 * rectangle we can position with `left/top/width/height: N%`.
 *
 * ASSUMED_PATCH_PIXEL_SIZE below is a placeholder: BigEarthNet Sentinel-2
 * 10m-band patches are 120x120px, which is what we assume until the real
 * patch imagery lands in this repo and a backend response can tell us the
 * true size per patch. If/when the API starts returning actual pixel
 * dimensions alongside evidence, replace this constant with that value —
 * every call site here takes pixelSize as a parameter specifically so that
 * swap doesn't require touching call sites, just what they pass in.
 */
export const ASSUMED_PATCH_PIXEL_SIZE = 120;

export interface PercentRect {
  leftPct: number;
  topPct: number;
  widthPct: number;
  heightPct: number;
}

/** Converts a [xMin, yMin, xMax, yMax] pixel-space bbox into a percentage
 *  rectangle suitable for absolutely positioning a <div> over an <img>
 *  that renders the full patch. */
export function bboxToPercentRect(
  bbox: [number, number, number, number],
  pixelSize: number = ASSUMED_PATCH_PIXEL_SIZE,
): PercentRect {
  const [xMin, yMin, xMax, yMax] = bbox;
  return {
    leftPct: (xMin / pixelSize) * 100,
    topPct: (yMin / pixelSize) * 100,
    widthPct: ((xMax - xMin) / pixelSize) * 100,
    heightPct: ((yMax - yMin) / pixelSize) * 100,
  };
}

/** Same idea for a single [x, y] point. */
export function pointToPercent(point: [number, number], pixelSize: number = ASSUMED_PATCH_PIXEL_SIZE): { leftPct: number; topPct: number } {
  const [x, y] = point;
  return { leftPct: (x / pixelSize) * 100, topPct: (y / pixelSize) * 100 };
}
