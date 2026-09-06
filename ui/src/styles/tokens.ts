/**
 * styles/tokens.ts
 * =================
 * The map's paint values, in one place.
 *
 * Colour tokens themselves live in styles/index.css as CSS variables (and
 * are exposed to Tailwind via tailwind.config.js) — but MapLibre paint
 * expressions are evaluated by WebGL, not CSS, so they cannot read a
 * var(--color-*). These constants are the one authorised transcription of
 * the Nocturne ramp into literal hex, purely for that reason. If a value
 * here disagrees with the stylesheet, the stylesheet wins and this file is
 * the bug.
 *
 * The state table below is exhaustive by design: every way a footprint or
 * overlay can look is enumerated here rather than being assembled ad hoc in
 * each layer, so "hovered" means the same thing on the map, in a context
 * chip and in the patch viewer.
 */

/** Nocturne ramp steps the map layers draw with. */
export const MAP_COLORS = {
  accent: "#9184d9",
  accent300: "#d2cefd",
  accent400: "#b5abfc",
  label: "#cfd3e5",
  labelHot: "#e7e5fe",
} as const;

export interface ShapePaint {
  fill: string;
  line: string;
  lineWidth: number;
  /** Present only on pending (unconfirmed) shapes — the shared dash. */
  dash?: [number, number];
}

/**
 * Footprint and overlay paint, keyed by state. Precedence when several
 * apply at once, highest first: pending > inContext > hovered > idle. The
 * dash on `pending` is the single signal for "not committed" and is reused
 * outside the map (upload dialog, confirm bar) — do not give it to a
 * committed shape.
 */
export const SHAPE_PAINT: Record<
  | "idle"
  | "hovered"
  | "inContext"
  | "pending"
  | "areaSelection"
  | "areaSelectionHot"
  | "evidence"
  | "evidenceHot",
  ShapePaint
> = {
  idle: { fill: "rgba(145,132,217,0.08)", line: "#9184d9", lineWidth: 1.25 },
  hovered: { fill: "rgba(145,132,217,0.18)", line: "#d2cefd", lineWidth: 2 },
  inContext: { fill: "rgba(145,132,217,0.26)", line: "#d2cefd", lineWidth: 2 },
  pending: { fill: "rgba(210,206,253,0.14)", line: "#d2cefd", lineWidth: 2, dash: [8, 5] },
  areaSelection: { fill: "rgba(181,171,252,0.14)", line: "#b5abfc", lineWidth: 1.5 },
  areaSelectionHot: { fill: "rgba(181,171,252,0.28)", line: "#b5abfc", lineWidth: 2.5 },
  evidence: { fill: "rgba(210,206,253,0.12)", line: "#d2cefd", lineWidth: 1.5 },
  evidenceHot: { fill: "rgba(210,206,253,0.30)", line: "#d2cefd", lineWidth: 2.5 },
};

/** Patch-id label paint for the footprint symbol layer. The halo keeps the
 *  label legible over arbitrary satellite imagery. */
export const LABEL_PAINT = {
  size: 15,
  color: MAP_COLORS.label,
  colorHot: MAP_COLORS.labelHot,
  haloColor: "rgba(0,0,0,0.65)",
  haloWidth: 1.5,
} as const;

/**
 * Per-composite placeholder gradients for the patch viewer preview, used
 * only until `GET /api/patches/:id/preview?composite=…` is serving real
 * imagery — they encode "which composite am I looking at" at a glance
 * without pretending to be data.
 */
export const COMPOSITE_PLACEHOLDER: Record<"true_color" | "false_color" | "sar", string> = {
  true_color: "linear-gradient(135deg,#292b31,#3f424d)",
  false_color: "linear-gradient(135deg,#423a6a,#2b2741)",
  sar: "linear-gradient(135deg,#3f424d,#1b1d2d)",
};
