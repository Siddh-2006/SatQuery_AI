/**
 * lib/resolvePatchOverlap.ts
 * =============================
 * The free-draw tool's client-side patch resolution (DESIGN.md §2.4): given
 * a hand-drawn polygon and the loaded footprint layer, find every patch it
 * overlaps using Turf's `booleanIntersects` — no network round-trip needed
 * just to know which patches a shape touches, since we already have the
 * footprints in memory.
 */
import { booleanIntersects, polygon as turfPolygon } from "@turf/turf";
import type { PatchFeatureCollection } from "../api/types";

/** @param vertices closed or open ring of [lng, lat] pairs (at least 3) */
export function resolvePatchOverlap(vertices: [number, number][], footprints: PatchFeatureCollection | null): string[] {
  if (!footprints || vertices.length < 3) return [];

  const ring = [...vertices];
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push(first); // turf requires a closed ring

  const drawn = turfPolygon([ring]);
  return footprints.features.filter((f) => booleanIntersects(drawn, f)).map((f) => f.properties.patchId);
}
