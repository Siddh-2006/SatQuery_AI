/**
 * state/useContextStore.ts
 * ==========================
 * Owns every ContextSet the researcher has built (DESIGN.md §4.1), which
 * one is "active" (i.e. will be attached to the next chat message), the
 * pairing guardrail, and any upload that's mid-flight (§4.2) before it's
 * confirmed into an item.
 *
 * Design choice worth flagging: adding a SECOND item is never silent. The
 * first item goes straight in — that's the common case and it should cost
 * one interaction. The second one opens the guardrail (see
 * api/pairOptions.ts), because at that moment the set's type is being
 * decided and only the researcher knows whether they meant "the same place
 * at two dates" or "two sensors over one place". Inferring it, as an
 * earlier revision did, silently produced bitemporal pairs whenever two
 * co-located patches were clicked, which is wrong about half the time and
 * invisible when it is.
 *
 * Sets are named ctx_1, ctx_2, … rather than with random ids: the name is
 * shown to the researcher in the set switcher and in the chat's status
 * line, so it has to be readable and stable in order.
 */
import { create } from "zustand";
import type { ContextItem, ContextSet, ContextType, UploadResponse } from "../api/types";
import { validateContextSet } from "../api/validateContextSet";
import { pairOptionsFor, type PairOptions, type PairType } from "../api/pairOptions";

export interface AddItemResult {
  ok: boolean;
  /** Present when ok is false — show this to the user as-is. */
  reason?: string;
  /** True when the add didn't happen because the guardrail took over; the
   *  caller should do nothing and let the dialog drive. */
  needsPairChoice?: boolean;
}

/** An upload in flight, from file-picked to either confirmed or discarded.
 *  See DESIGN.md §4.2 for the full flow this backs. */
export interface PendingUpload {
  status: "uploading" | "ready" | "error";
  file: File;
  /** 0-100, for the dialog's progress bar. */
  progress: number;
  result?: UploadResponse;
  error?: string;
  /** Manual overrides the researcher fills in when the backend couldn't
   *  detect them (e.g. modality for a benchmark PNG with no geo-tags). */
  manualModality?: "optical" | "sar";
  manualTimestamp?: string;
}

/** The guardrail's in-flight question: "this item wants to join a set that
 *  already has one — as what?" */
export interface PairPrompt {
  candidate: ContextItem;
  existing: ContextItem;
  options: PairOptions;
}

interface ContextState {
  contextSets: ContextSet[];
  activeContextSetId: string | null;

  /** Hover id shared with the context-chip list and the map/drawer overlay
   *  highlight (DESIGN.md §3.2 / §4.3). Only round-trips onto the map for
   *  `kind: "patch"` items, whose id is a real patchId the footprint layer
   *  also keys on — area-selection and upload chips highlight themselves
   *  but have no footprint to light up. */
  hoveredContextItemId: string | null;
  setHoveredContextItemId: (id: string | null) => void;

  getActiveContextSet: () => ContextSet | null;
  setActiveContextSet: (id: string) => void;

  createContextSet: (type?: ContextType) => string;
  deleteContextSet: (id: string) => void;

  /** Adds `item` to the active set, creating a "single" set first if there
   *  isn't one. When the set already holds an item this opens the pairing
   *  guardrail instead of guessing, and returns needsPairChoice. */
  addItemToActiveSet: (item: ContextItem) => AddItemResult;
  removeItem: (contextSetId: string, itemIndex: number) => void;

  // --- pairing guardrail (§4.1) ---------------------------------------
  pairPrompt: PairPrompt | null;
  /** Commits the pending candidate as the given pair type. */
  resolvePairAs: (type: PairType) => AddItemResult;
  /** Drops the set's existing item and keeps the candidate instead. */
  replaceWithCandidate: () => void;
  cancelPairPrompt: () => void;

  // --- pending upload (§4.2) ------------------------------------------
  /** The upload dialog's own open state, separate from pendingUpload:
   *  the dialog opens empty (a dropzone) before any file exists, and stays
   *  open through upload and manual metadata entry until the researcher
   *  either adds the result to context or discards it. */
  uploadDialogOpen: boolean;
  openUploadDialog: () => void;
  closeUploadDialog: () => void;
  pendingUpload: PendingUpload | null;
  setPendingUpload: (upload: PendingUpload | null) => void;
  patchPendingUpload: (patch: Partial<PendingUpload>) => void;
  clearPendingUpload: () => void;

  // --- session hydration (§8) -----------------------------------------
  hydrate: (contextSets: ContextSet[], activeContextSetId: string | null) => void;
  reset: () => void;
}

/** ctx_1, ctx_2, … — the lowest number not already taken, so deleting a set
 *  and making another doesn't produce a duplicate name. */
function nextSetName(existing: ContextSet[]): string {
  const taken = new Set(existing.map((s) => s.id));
  for (let n = 1; ; n++) {
    const id = `ctx_${n}`;
    if (!taken.has(id)) return id;
  }
}

function replaceSet(sets: ContextSet[], next: ContextSet): ContextSet[] {
  return sets.map((s) => (s.id === next.id ? next : s));
}

export const useContextStore = create<ContextState>((set, get) => ({
  contextSets: [],
  activeContextSetId: null,

  hoveredContextItemId: null,
  setHoveredContextItemId: (id) => set({ hoveredContextItemId: id }),

  getActiveContextSet: () => {
    const { contextSets, activeContextSetId } = get();
    return contextSets.find((c) => c.id === activeContextSetId) ?? null;
  },
  setActiveContextSet: (id) => set({ activeContextSetId: id }),

  createContextSet: (type = "single") => {
    const id = nextSetName(get().contextSets);
    set((s) => ({ contextSets: [...s.contextSets, { id, type, items: [] }], activeContextSetId: id }));
    return id;
  },

  deleteContextSet: (id) =>
    set((s) => ({
      contextSets: s.contextSets.filter((c) => c.id !== id),
      activeContextSetId: s.activeContextSetId === id ? (s.contextSets.find((c) => c.id !== id)?.id ?? null) : s.activeContextSetId,
    })),

  addItemToActiveSet: (item) => {
    const state = get();
    let active = state.getActiveContextSet();

    if (!active) {
      const id = state.createContextSet("single");
      active = { id, type: "single", items: [] };
    }

    if (active.items.length === 0) {
      const next: ContextSet = { ...active, type: "single", items: [item] };
      set((s) => ({ contextSets: replaceSet(s.contextSets, next) }));
      return { ok: true };
    }

    if (active.items.length >= 2) {
      return {
        ok: false,
        reason: "This context already has two items — remove one first.",
      };
    }

    // One item present: the set's type is about to be decided, so ask.
    set({
      pairPrompt: {
        candidate: item,
        existing: active.items[0],
        options: pairOptionsFor(active.items[0], item),
      },
    });
    return { ok: false, needsPairChoice: true };
  },

  removeItem: (contextSetId, itemIndex) =>
    set((s) => ({
      contextSets: s.contextSets.map((c) => {
        if (c.id !== contextSetId) return c;
        const items = c.items.filter((_, i) => i !== itemIndex);
        // Dropping back to 0-1 items always makes a set valid again as
        // "single" (or empty, ready to receive a fresh first item).
        return { ...c, type: items.length <= 1 ? "single" : c.type, items };
      }),
    })),

  pairPrompt: null,

  resolvePairAs: (type) => {
    const { pairPrompt, getActiveContextSet } = get();
    const active = getActiveContextSet();
    if (!pairPrompt || !active) return { ok: false, reason: "Nothing to pair." };

    const candidate: ContextSet = { ...active, type, items: [...active.items, pairPrompt.candidate] };
    // Belt-and-braces: pairOptionsFor already filtered the offer, but the
    // authoritative structural check still runs before anything is stored.
    const validation = validateContextSet(candidate);
    if (!validation.valid) return { ok: false, reason: validation.reason };

    set((s) => ({ contextSets: replaceSet(s.contextSets, candidate), pairPrompt: null }));
    return { ok: true };
  },

  replaceWithCandidate: () => {
    const { pairPrompt, getActiveContextSet } = get();
    const active = getActiveContextSet();
    if (!pairPrompt || !active) return;
    const next: ContextSet = { ...active, type: "single", items: [pairPrompt.candidate] };
    set((s) => ({ contextSets: replaceSet(s.contextSets, next), pairPrompt: null }));
  },

  cancelPairPrompt: () => set({ pairPrompt: null }),

  uploadDialogOpen: false,
  openUploadDialog: () => set({ uploadDialogOpen: true }),
  // Closing always drops the pending upload: a file the researcher walked
  // away from is not something to silently resurrect next time.
  closeUploadDialog: () => set({ uploadDialogOpen: false, pendingUpload: null }),

  pendingUpload: null,
  setPendingUpload: (upload) => set({ pendingUpload: upload }),
  patchPendingUpload: (patch) =>
    set((s) => (s.pendingUpload ? { pendingUpload: { ...s.pendingUpload, ...patch } } : {})),
  clearPendingUpload: () => set({ pendingUpload: null }),

  hydrate: (contextSets, activeContextSetId) =>
    set({ contextSets, activeContextSetId, pendingUpload: null, pairPrompt: null, uploadDialogOpen: false }),
  reset: () =>
    set({ contextSets: [], activeContextSetId: null, pendingUpload: null, pairPrompt: null, uploadDialogOpen: false }),
}));
