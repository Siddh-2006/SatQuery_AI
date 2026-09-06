/**
 * mocks/fixtures/patches.ts
 * ==========================
 * Mock patch index for the map's footprint layer (DESIGN.md §2.1) — now
 * backed by the REAL delivered dataset: every Sentinel-1/Sentinel-2 patch
 * BigEarthNet cut over Kosovo (UTM tile 34TEN, 1,616 patches) and
 * Luxembourg (UTM tile 31UGR, 1,814 patches), read straight out of the
 * `BigEarthNet-*-S1.zip` / `BigEarthNet-*-S2.zip` archives.
 *
 * `real-patches/{kosovo,luxembourg}.json` hold the extracted-once data: each
 * patch's true WGS84 footprint (reprojected from the GeoTIFFs' own UTM
 * geotransform — not approximated), which sensor(s) cover it, and every
 * real capture date found in the archives. Regenerate them with
 * `extract_patches.py` if the source zips change; nothing else in this file
 * needs to.
 *
 * Every other file in the app (map layers, context store, chat) only ever
 * talks to the `PatchFeatureCollection` / `TimeseriesEntry` shapes from
 * `api/types.ts`, never to this fixture directly — so pointing the real
 * backend at `/api/patches` later requires zero component changes.
 */
import type { Modality, PatchFeatureCollection, TimeseriesEntry } from "../../api/types";
import { placeholderPreview } from "../placeholderImage";
import kosovoPatches from "./real-patches/kosovo.json";
import luxembourgPatches from "./real-patches/luxembourg.json";

type RegionCode = "KOS" | "LUX";

interface RawPatch {
  patchId: string;
  region: RegionCode;
  tile: string;
  row: number;
  col: number;
  lat: number;
  lon: number;
  /** Closed WGS84 ring, [lon, lat] pairs — exactly what the source GeoTIFF's
   *  own geotransform says, reprojected; not a hand-picked square. */
  polygon: [number, number][];
  modalities: Modality[];
  /** Every real ISO capture date found across both sensors' archives for
   *  this patch. */
  timestamps: string[];
}

const REGION_LABEL: Record<RegionCode, string> = { KOS: "Kosovo", LUX: "Luxembourg" };

function labelFor(p: RawPatch): string {
  return `${REGION_LABEL[p.region]} — tile ${p.tile} (row ${p.row}, col ${p.col})`;
}

const ALL_PATCHES: RawPatch[] = [...(kosovoPatches as RawPatch[]), ...(luxembourgPatches as RawPatch[])];

/** Built once at module load — this is the mock "database" the MSW
 *  handlers in mocks/handlers.ts read from. */
export const MOCK_PATCH_COLLECTION: PatchFeatureCollection = {
  type: "FeatureCollection",
  features: ALL_PATCHES.map((p) => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [p.polygon] },
    properties: {
      patchId: p.patchId,
      lat: p.lat,
      lon: p.lon,
      availableModalities: p.modalities,
      availableTimestamps: p.timestamps,
      label: labelFor(p),
    },
  })),
};

/** patchId -> its full record, for handlers that need timestamps/label
 *  lookups (preview, timeseries) without re-scanning the FeatureCollection. */
export const MOCK_PATCH_BY_ID: Record<string, RawPatch> = Object.fromEntries(
  ALL_PATCHES.map((p) => [p.patchId, p]),
);

/** GET /api/patches/:id/timeseries mock data: every real capture at the
 *  same location as `patchId`, oldest first. */
export function mockTimeseriesFor(patchId: string): TimeseriesEntry[] {
  const p = MOCK_PATCH_BY_ID[patchId];
  if (!p) return [];
  return p.timestamps.map((timestamp) => ({
    patchId: p.patchId,
    timestamp,
    thumbnailUrl: placeholderPreview(`${p.patchId} · ${timestamp}`, 128, 128),
  }));
}
