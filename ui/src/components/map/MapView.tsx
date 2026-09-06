/**
 * components/map/MapView.tsx
 * ============================
 * The centre panel (DESIGN.md §2). Owns the MapLibre instance and the
 * basemap layer; everything else — footprints, the three tools, the
 * pending confirm bar, the popover, the viewer drawer — is a child that
 * receives the created `map` and manages its own layers and listeners.
 *
 * Two structural decisions worth keeping:
 *
 *  - The toolbar sits ABOVE the map frame, not floating over the imagery.
 *    Tools change what a click means, so the control that switches them
 *    should never be something you might click the map through.
 *  - The drawer is anchored to the map FRAME, not the window. It is a view
 *    onto the thing the map is showing, so it belongs inside the map's
 *    bounds, and it leaves the left and right panels untouched while open.
 *
 * The map instance is handed to children only after MapLibre's "load"
 * event, so every child can assume it is ready to have sources added.
 */
import { useEffect, useReducer, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { useMapStore, REGIONS } from "../../state/useMapStore";
import { PatchFootprintLayer } from "./PatchFootprintLayer";
import { PatchPopover } from "./PatchPopover";
import { SelectionToolbar } from "./SelectionToolbar";
import { FreeDrawTool } from "./FreeDrawTool";
import { PointSegmentTool } from "./PointSegmentTool";
import { PendingSelectionLayer } from "./PendingSelectionLayer";
import { PatchViewerDrawer } from "../viewer/PatchViewerDrawer";

const BASEMAP_SOURCE_ID = "basemap";
const BASEMAP_LAYER_ID = "basemap-layer";

/** Raster tile templates for the two basemap options (§2.7). Esri World
 *  Imagery needs no API key; "streets" is for orientation when imagery is
 *  too busy to read footprint outlines against. */
const TILE_URLS: Record<"satellite" | "streets", string> = {
  satellite: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  streets: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
};

/** Resolution preset -> how far the basemap is allowed to zoom. This is a
 *  view setting only: the patch rasters' own resolution is a property of
 *  the data, so nothing outside the basemap reads it. */
const MAX_ZOOM_BY_RESOLUTION: Record<"10m" | "20m" | "60m", number> = { "10m": 18, "20m": 16, "60m": 13 };

/**
 * Glyphs for the footprint layer's patch-id labels. MapLibre rasterises
 * label text from SDF glyph PBFs, which means it cannot use the page's
 * webfont — Inter would have to be served as a glyph range from our own
 * host. Until that exists we borrow MapLibre's public demo glyph server,
 * and the label's colour/halo (styles/tokens.ts LABEL_PAINT) carries the
 * design instead of its typeface. Replace this URL with a self-hosted
 * Inter glyph endpoint when one is available.
 */
const GLYPHS_URL = "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf";

export function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [map, setMap] = useState<maplibregl.Map | null>(null);
  const basemapStyle = useMapStore((s) => s.basemapStyle);
  const resolution = useMapStore((s) => s.resolution);
  const region = useMapStore((s) => s.region);

  // Forces anything positioned via map.project (the popover, the pending
  // confirm bar) to recompute whenever the map moves.
  const [, forceRerender] = useReducer((n: number) => n + 1, 0);

  // --- Create the map once ------------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    const instance = new maplibregl.Map({
      container: containerRef.current,
      style: { version: 8, glyphs: GLYPHS_URL, sources: {}, layers: [] },
      bounds: REGIONS.LUX.bbox,
      fitBoundsOptions: { padding: 48 },
      attributionControl: { compact: true },
    });
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    instance.on("load", () => setMap(instance));
    instance.on("move", forceRerender);

    // Dev-only debug hook — drive the map from the console or a test via
    // window.__satqueryMap without shipping test-only code (Vite strips
    // import.meta.env.DEV branches at build time).
    if (import.meta.env.DEV) {
      (window as unknown as { __satqueryMap?: maplibregl.Map }).__satqueryMap = instance;
    }

    return () => instance.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once.
  }, []);

  // --- Keep the basemap layer in sync with style/resolution ---------------
  useEffect(() => {
    if (!map) return;
    // Remove-and-re-add is the one approach that behaves identically across
    // maplibre-gl versions; mutating a raster source's tiles in place is not
    // consistently supported.
    if (map.getLayer(BASEMAP_LAYER_ID)) map.removeLayer(BASEMAP_LAYER_ID);
    if (map.getSource(BASEMAP_SOURCE_ID)) map.removeSource(BASEMAP_SOURCE_ID);

    map.addSource(BASEMAP_SOURCE_ID, {
      type: "raster",
      tiles: [TILE_URLS[basemapStyle]],
      tileSize: 256,
      maxzoom: MAX_ZOOM_BY_RESOLUTION[resolution],
      attribution: basemapStyle === "satellite" ? "Esri World Imagery" : "© OpenStreetMap contributors",
    });
    // Insert beneath the tool overlay layers if they already exist, so
    // re-running this never paints the basemap over them. The patch
    // footprints themselves are no longer a MapLibre layer at all (see
    // PatchFootprintLayer's header) — they're a DOM canvas stacked via CSS,
    // so they don't need an anchor here. "free-draw-line" is the earliest
    // layer any child still adds via MapLibre (mounted before this effect
    // runs, since child effects fire before their parent's in one commit).
    map.addLayer(
      { id: BASEMAP_LAYER_ID, type: "raster", source: BASEMAP_SOURCE_ID },
      map.getLayer("free-draw-line") ? "free-draw-line" : undefined,
    );
  }, [map, basemapStyle, resolution]);

  // --- Region select drives the viewport ---------------------------------
  useEffect(() => {
    if (!map) return;
    map.fitBounds(REGIONS[region].bbox, { padding: 48, duration: 600 });
  }, [map, region]);

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <SelectionToolbar />

      <div className="elev-sm relative mx-[11.2px] mb-[11.2px] min-h-0 flex-1 overflow-hidden rounded-md">
        <div
          ref={containerRef}
          className="h-full w-full"
          // The streets basemap is desaturated so the accent footprint
          // outlines stay the most saturated thing on screen.
          style={basemapStyle === "streets" ? { filter: "saturate(.15) brightness(.85)" } : undefined}
        />

        <p className="pointer-events-none absolute bottom-[8.4px] left-[11.2px] right-[80px] m-0 text-[10.5px] leading-[1.45] text-neutral-400 [text-shadow:0_1px_3px_rgba(0,0,0,.8)]">
          Basemap: {basemapStyle === "satellite" ? "Esri World Imagery" : "OpenStreetMap"} — orientation only, never read
          as pixel data · Footprints: /api/patches?bbox={REGIONS[region].bbox.join(",")}
        </p>

        {map && (
          <>
            <PatchFootprintLayer map={map} />
            <FreeDrawTool map={map} />
            <PointSegmentTool map={map} />
            <PendingSelectionLayer map={map} />
            <PatchPopover map={map} />
            <PatchViewerDrawer />
          </>
        )}
      </div>
    </div>
  );
}
