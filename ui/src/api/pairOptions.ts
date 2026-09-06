/**
 * api/pairOptions.ts
 * ===================
 * Works out what a two-item context set COULD be, and — just as
 * importantly — why each option it can't be is unavailable.
 *
 * validateContextSet.ts answers "is this set, as declared, structurally
 * valid?". This file answers the question the UI actually asks when a
 * researcher adds a second item: "which pair types can these two form?" It
 * exists so the pairing guardrail dialog (components/context/PairTypeDialog)
 * can offer only the pair types that will pass validation while still
 * listing every blocked option with its reason, rather than silently hiding
 * choices — a researcher who expected a bitemporal pair needs to be told it
 * was the identical capture date that stopped them, not left guessing.
 *
 * The reason strings below are user-facing copy, transcribed from the
 * design handoff. Keep them; they are the whole point of the file.
 *
 * Deliberately does NOT: mutate any store, decide what to do about the
 * answer, or re-check anything the server will re-check anyway.
 */
import type { ContextItem, ContextType, Modality } from "./types";

export type PairType = Extract<ContextType, "bitemporal_pair" | "cross_modal_pair">;

export interface BlockedPairOption {
  type: PairType;
  /** Safe to show as-is. */
  reason: string;
}

export interface PairOptions {
  /** Pair types these two items can actually form, in offer order. */
  allowed: PairType[];
  /** Every type that isn't allowed, with the reason it isn't. */
  blocked: BlockedPairOption[];
}

const REASON = {
  areaSelection:
    "Area selections may only sit in a single-item context set — matching a hand-drawn shape across dates or modalities is out of v1 scope (§4.1).",
  unlocatedUpload:
    "An upload with no detected location can only be used in a single context set — there is no location to match it by.",
  differentLocations:
    "These items sit at different locations. Both pair types require the same place, so neither is offered.",
  sameDate:
    "Bitemporal pair needs two different capture dates — use the temporal browser to add a second timestamp.",
  missingModality: "Cross-modal pair needs both SAR and optical coverage across the two items.",
} as const;

export const PAIR_TYPE_LABEL: Record<PairType, string> = {
  bitemporal_pair: "bitemporal pair",
  cross_modal_pair: "cross-modal pair",
};

function location(item: ContextItem): { lat: number; lon: number } | null {
  if (item.kind === "patch") return { lat: item.lat, lon: item.lon };
  if (item.kind === "uploaded_image") return item.detectedLocation;
  return null;
}

function timestamp(item: ContextItem): string | null {
  if (item.kind === "patch") return item.timestamp;
  if (item.kind === "uploaded_image") return item.detectedTimestamp;
  return null;
}

/** What this item contributes to the pair's modality coverage. A patch
 *  restricted to `sar_only` contributes SAR alone even though the patch
 *  itself carries both — the band selection is a real narrowing, not a
 *  display preference (DESIGN.md §2.3). */
function modalities(item: ContextItem): Modality[] {
  if (item.kind === "patch") {
    return item.bandSelection === "sar_only" ? ["sar"] : item.availableModalities;
  }
  if (item.kind === "uploaded_image") return item.detectedModality ? [item.detectedModality] : [];
  return [];
}

const SAME_LOCATION_EPSILON_DEG = 1e-4; // ~11 m — float rounding is "the same place"

function sameLocation(a: { lat: number; lon: number }, b: { lat: number; lon: number }): boolean {
  return (
    Math.abs(a.lat - b.lat) < SAME_LOCATION_EPSILON_DEG &&
    Math.abs(a.lon - b.lon) < SAME_LOCATION_EPSILON_DEG
  );
}

/** Human label for a context item, for the guardrail's "Pairing A with B". */
export function describeItem(item: ContextItem): string {
  if (item.kind === "patch") return `${item.patchId} · ${item.timestamp}`;
  if (item.kind === "uploaded_image") return item.originalFilename;
  return item.method === "free_draw" ? "Free-draw area" : "Segmented mask";
}

/** Evaluates `existing` + `candidate` against both pair types. */
export function pairOptionsFor(existing: ContextItem, candidate: ContextItem): PairOptions {
  const blockBoth = (reason: string): PairOptions => ({
    allowed: [],
    blocked: [
      { type: "bitemporal_pair", reason },
      { type: "cross_modal_pair", reason },
    ],
  });

  if (existing.kind === "area_selection" || candidate.kind === "area_selection") {
    return blockBoth(REASON.areaSelection);
  }

  const locA = location(existing);
  const locB = location(candidate);
  if (!locA || !locB) return blockBoth(REASON.unlocatedUpload);
  if (!sameLocation(locA, locB)) return blockBoth(REASON.differentLocations);

  const allowed: PairType[] = [];
  const blocked: BlockedPairOption[] = [];

  const tsA = timestamp(existing);
  const tsB = timestamp(candidate);
  if (tsA && tsB && tsA !== tsB) allowed.push("bitemporal_pair");
  else blocked.push({ type: "bitemporal_pair", reason: REASON.sameDate });

  const covered = new Set<Modality>([...modalities(existing), ...modalities(candidate)]);
  if (covered.has("optical") && covered.has("sar")) allowed.push("cross_modal_pair");
  else blocked.push({ type: "cross_modal_pair", reason: REASON.missingModality });

  return { allowed, blocked };
}
