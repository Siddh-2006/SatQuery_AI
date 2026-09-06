/**
 * api/validateContextSet.ts
 * ==========================
 * Client-side mirror of the validation rules in DESIGN.md §6.2. This is
 * fast local feedback ONLY — it exists so the UI can stop a researcher
 * before they submit an impossible request (grey out a button, show a
 * message inline), never as the authoritative check. The orchestrator
 * always re-validates server-side and is free to reject things this
 * function lets through (e.g. two co-located but otherwise incompatible
 * patches) — see ApiError / the `incompatible_context` error code.
 *
 * Used by:
 *  - useContextStore, when deciding whether an item can be added to a set
 *    (the guardrail described in DESIGN.md §4.1).
 *  - ChatPanel, to decide whether the prompt input should be enabled.
 */
import type { ContextItem, ContextSet } from "./types";

export interface ValidationResult {
  valid: boolean;
  /** Empty when valid. Shown to the user as-is when not. */
  reason?: string;
}

function itemLocation(item: ContextItem): { lat: number; lon: number } | null {
  if (item.kind === "patch") return { lat: item.lat, lon: item.lon };
  if (item.kind === "uploaded_image") return item.detectedLocation;
  return null; // area_selection has no single lat/lon of its own
}

function itemModalities(item: ContextItem): string[] {
  if (item.kind === "patch") return item.availableModalities;
  if (item.kind === "uploaded_image") return item.detectedModality ? [item.detectedModality] : [];
  return [];
}

const SAME_LOCATION_EPSILON_DEG = 1e-4; // ~11m — treats float rounding as "the same place"

function sameLocation(a: { lat: number; lon: number }, b: { lat: number; lon: number }): boolean {
  return Math.abs(a.lat - b.lat) < SAME_LOCATION_EPSILON_DEG && Math.abs(a.lon - b.lon) < SAME_LOCATION_EPSILON_DEG;
}

/**
 * Checks whether `set` is internally consistent for its declared `type`.
 * Does NOT check "is this a good idea for the query" — only structural
 * validity, matching the bullet list in DESIGN.md §6.2.
 */
export function validateContextSet(set: ContextSet): ValidationResult {
  const expectedLength = set.type === "single" ? 1 : 2;
  if (set.items.length !== expectedLength) {
    return {
      valid: false,
      reason: `A "${set.type}" context set needs exactly ${expectedLength} item(s), found ${set.items.length}.`,
    };
  }

  if (set.type !== "single") {
    // v1 restriction (DESIGN.md §4.1): area selections only allowed in
    // "single" sets — free-drawn/segmented regions aren't well-defined
    // across time or across a cross-modal pairing yet.
    const areaSelection = set.items.find((item) => item.kind === "area_selection");
    if (areaSelection) {
      return {
        valid: false,
        reason: "An area selection (free draw / point segment) can only be used in a single-image context, not a pair.",
      };
    }

    // Uploaded images with no detected location can't be matched by
    // location, so they're single-only too — this falls out of the
    // location-matching rule below, but we surface a clearer message here.
    const unlocatedUpload = set.items.find((item) => item.kind === "uploaded_image" && !item.detectedLocation);
    if (unlocatedUpload) {
      return {
        valid: false,
        reason: "This uploaded image has no detected location, so it can only be used in a single-image context.",
      };
    }
  }

  if (set.type === "bitemporal_pair") {
    const [a, b] = set.items;
    const locA = itemLocation(a);
    const locB = itemLocation(b);
    if (!locA || !locB || !sameLocation(locA, locB)) {
      return { valid: false, reason: "Bitemporal analysis requires both items to be the same location, at different times." };
    }
  }

  if (set.type === "cross_modal_pair") {
    const modalities = new Set(set.items.flatMap(itemModalities));
    if (!modalities.has("optical") || !modalities.has("sar")) {
      return { valid: false, reason: "Cross-modal analysis requires both optical and SAR bands across the two items." };
    }
  }

  return { valid: true };
}
