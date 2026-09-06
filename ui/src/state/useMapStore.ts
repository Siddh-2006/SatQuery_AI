/**
 * state/useMapStore.ts
 * =====================
 * Everything about the centre panel that isn't "what's in context" (that
 * lives in useContextStore) or "what's been said" (useChatStore). See
 * DESIGN.md §5 for why these are kept as separate stores.
 *
 * Owns:
 *  - the loaded patch footprints (from GET /api/patches)
 *  - hover state, shared with the left-panel context chips so hovering
 *    either highlights the other (DESIGN.md §3.2/§4.3's hover-link)
 *  - which tool is active in the selection toolbar (§2.2)
 *  - the current PENDING selection — a dashed, not-yet-confirmed shape a
 *    tool is mid-way through. Confirming it turns it into a ContextItem
 *    (via useContextStore); cancelling/Escape just clears it here.
 *  - the Patch Viewer Drawer's open/closed state and its band composite
 *    (§2.6)
 *  - the three view controls in the top bar (basemap, region, resolution),
 *    none of which change WHICH data is selectable — only how it's drawn
 *    and where the viewport starts.
 */
import { create } from "zustand";
import type { PatchFeatureCollection, SelectionMethod } from "../api/types";

/**
 * A selection tool's in-progress result, before the user confirms
 * "Add to context". `method` mirrors AreaSelectionRef's `method`, but this
 * type is UI-only — it becomes an AreaSelectionRef only on confirm, once
 * we know which ContextSet it's joining.
 */
export interface PendingAreaSelection {
  method: Extract<SelectionMethod, "free_draw" | "point_segment">;
  geometry: GeoJSON.Polygon;
  resolvedPatchIds: string[];
  /** Only present for "point_segment". */
  confidence?: number;
}

export type BandComposite = "true_color" | "false_color" | "sar";
export type RegionKey = "LUX" | "KOS";

/**
 * The three real selection tools from `SelectionMethod` (api/types.ts —
 * the backend contract), plus a fourth, UI-only "none" state: no tool
 * intercepts clicks/hover at all, so panning/zooming a patch-dense area
 * doesn't fight with a footprint's popover or hover tooltip on every
 * click. "none" is never sent to the backend and never appears in
 * `SelectionMethod` — it's purely `activeTool`'s own resting state.
 */
export type MapTool = SelectionMethod | "none";

/**
 * The two regions the fixture patches sit in — the exact WGS84 extent of
 * each region's full BigEarthNet S1/S2 patch grid (Luxembourg: UTM tile
 * 31UGR, Kosovo: UTM tile 34TEN), not an approximation. The bbox is what a
 * real deployment would send as `GET /api/patches?bbox=…`; here it doubles
 * as the viewport the region select flies to, so picking a region actually
 * takes the researcher there instead of just filtering silently.
 */
export const REGIONS: Record<RegionKey, { label: string; bbox: [number, number, number, number] }> = {
  LUX: { label: "Luxembourg", bbox: [5.764458, 49.521345, 6.546574, 50.143944] },
  KOS: { label: "Kosovo", bbox: [20.999755, 42.367995, 21.761384, 43.082705] },
};

interface MapState {
  footprints: PatchFeatureCollection | null;
  setFootprints: (fc: PatchFeatureCollection) => void;

  /** Basemap style toggle (§2.7) — purely visual, never affects which
   *  patch data is selectable. "satellite" = Esri World Imagery (the
   *  locked-in default), "streets" = a plain OSM raster, desaturated, for
   *  when imagery is too busy to read footprint outlines against. */
  basemapStyle: "satellite" | "streets";
  setBasemapStyle: (style: "satellite" | "streets") => void;

  /** Which region's bbox the footprint query and viewport are scoped to. */
  region: RegionKey;
  setRegion: (region: RegionKey) => void;

  /** Display resolution preset. Affects the basemap's max zoom only — the
   *  patch data's own resolution is a property of the raster, not a view
   *  setting, so nothing downstream of the map reads this. */
  resolution: "10m" | "20m" | "60m";
  setResolution: (resolution: "10m" | "20m" | "60m") => void;

  /** Shared hover id — set by hovering either a map footprint/pending
   *  shape OR a left-panel context chip; consumed by both to draw the
   *  matching highlight. Distinct from chat's hoveredEvidenceId
   *  (useChatStore) because these are different id namespaces. */
  hoveredPatchId: string | null;
  setHoveredPatchId: (id: string | null) => void;

  /** The patch a popover (§2.3) or drawer (§2.6) is currently showing. */
  activePatchId: string | null;
  popoverOpen: boolean;
  openPopoverFor: (patchId: string) => void;
  closePopover: () => void;

  /** Which location the Temporal Browser (§4.4) is showing captures for —
   *  set from the map via a footprint popover's "Add to temporal explorer"
   *  (finds every other capture at that SAME location), rather than making
   *  the researcher pick one out of a location list with thousands of
   *  entries. Null clears it back to the "pick a patch on the map" state. */
  temporalPatchId: string | null;
  setTemporalPatchId: (patchId: string | null) => void;

  drawerOpen: boolean;
  openDrawerFor: (patchId: string) => void;
  closeDrawer: () => void;

  /** Which composite the drawer's preview requests (§2.6). Lives here, not
   *  in the drawer, so it survives the drawer being closed and reopened —
   *  a researcher comparing SAR across patches shouldn't be reset to true
   *  colour on every open. */
  composite: BandComposite;
  setComposite: (composite: BandComposite) => void;

  /** Which map tool is currently selected (§2.2), or "none" — see MapTool. */
  activeTool: MapTool;
  setActiveTool: (tool: MapTool) => void;

  /** Whether the footprint overlay (PatchFootprintLayer's yellow borders)
   *  draws at all. Independent of `activeTool`: this hides the visual
   *  layer entirely (e.g. to see the bare basemap under a dense patch
   *  grid), whereas `activeTool: "none"` keeps the borders visible but
   *  stops them intercepting clicks/hover. */
  showFootprints: boolean;
  setShowFootprints: (show: boolean) => void;
  toggleShowFootprints: () => void;

  /** The dashed, unconfirmed shape a free-draw/point-segment tool is
   *  holding. Null when nothing is pending. */
  pendingSelection: PendingAreaSelection | null;
  setPendingSelection: (selection: PendingAreaSelection | null) => void;
  clearPendingSelection: () => void;

  /** In-progress free-draw vertices ([lng, lat] pairs), before the polygon
   *  is closed into a pendingSelection. Lives here rather than as local
   *  state in FreeDrawTool so the toolbar hint and a global
   *  Escape-to-cancel can both reach it without prop drilling. Always
   *  empty when activeTool !== "free_draw". */
  freeDrawVertices: [number, number][];
  addFreeDrawVertex: (vertex: [number, number]) => void;
  resetFreeDraw: () => void;

  /** Everything Escape clears, in one action: the popover, the pending
   *  shape and any half-drawn polygon. Bound once in App.tsx so every
   *  tool gets the same escape behaviour for free (§2.2). */
  clearTransientMapState: () => void;
}

export const useMapStore = create<MapState>((set) => ({
  footprints: null,
  setFootprints: (fc) => set({ footprints: fc }),

  basemapStyle: "satellite",
  setBasemapStyle: (style) => set({ basemapStyle: style }),

  region: "LUX",
  // Switching region invalidates anything half-drawn: the vertices refer to
  // coordinates the researcher can no longer see.
  setRegion: (region) => set({ region, pendingSelection: null, freeDrawVertices: [], popoverOpen: false }),

  resolution: "10m",
  setResolution: (resolution) => set({ resolution }),

  hoveredPatchId: null,
  setHoveredPatchId: (id) => set({ hoveredPatchId: id }),

  activePatchId: null,
  popoverOpen: false,
  openPopoverFor: (patchId) => set({ activePatchId: patchId, popoverOpen: true }),
  closePopover: () => set({ popoverOpen: false }),

  temporalPatchId: null,
  setTemporalPatchId: (patchId) => set({ temporalPatchId: patchId }),

  drawerOpen: false,
  openDrawerFor: (patchId) => set({ activePatchId: patchId, drawerOpen: true, popoverOpen: false }),
  closeDrawer: () => set({ drawerOpen: false }),

  composite: "true_color",
  setComposite: (composite) => set({ composite }),

  activeTool: "footprint",
  setActiveTool: (tool) => set({ activeTool: tool, pendingSelection: null, freeDrawVertices: [], popoverOpen: false }),

  showFootprints: true,
  setShowFootprints: (show) => set({ showFootprints: show }),
  toggleShowFootprints: () => set((s) => ({ showFootprints: !s.showFootprints })),

  pendingSelection: null,
  setPendingSelection: (selection) => set({ pendingSelection: selection }),
  clearPendingSelection: () => set({ pendingSelection: null }),

  freeDrawVertices: [],
  addFreeDrawVertex: (vertex) => set((s) => ({ freeDrawVertices: [...s.freeDrawVertices, vertex] })),
  resetFreeDraw: () => set({ freeDrawVertices: [] }),

  clearTransientMapState: () =>
    set({ popoverOpen: false, pendingSelection: null, freeDrawVertices: [], hoveredPatchId: null }),
}));
