# SatQuery AI — Frontend

The web UI for SatQuery AI (see `../SIH Idea doc.docx` for the full problem
statement). **Read [DESIGN.md](./DESIGN.md) first** — it's the actual design
document (layout, data model, full API contract) that every file in `src/`
implements. This README only covers running the project and the handful of
implementation shortcuts taken to get a working v1 out quickly.

## Running it

```bash
npm install
npx msw init public/ --save   # one-time: generates public/mockServiceWorker.js
npm run dev
```

Then open the printed local URL. In development the app runs entirely
against a **mock backend** (Mock Service Worker, see `src/mocks/`) — there
is no real orchestrator to run yet, so every `/api/...` call in
DESIGN.md §6 is answered by fixture data and simple pattern-matching
instead. This means the whole UI (map, context, chat, sessions, uploads) is
clickable and demoable right now, with placeholder patch imagery standing
in for the real thing.

`npm run lint` type-checks the project (`tsc --noEmit`) without building —
run this before committing.

## Where the real patch imagery goes

`src/mocks/fixtures/patches.ts` currently defines a handful of fake patch
footprints around Luxembourg and Kosovo (matching the two BigEarthNet
regions named in the problem statement), and every "preview" image in the
app is a generated placeholder tile (see `src/mocks/placeholderImage.ts`) —
there is no real Sentinel-1/2 imagery checked in yet. When the real dataset
lands in the working directory, only `mocks/fixtures/patches.ts` and the
mock preview/timeseries handlers in `mocks/handlers.ts` need to change —
every component reads exclusively through `api/client.ts` and
`api/types.ts`, never straight from a fixture file, so swapping the data
source doesn't touch component code.

## Swapping the mock backend for the real orchestrator

1. Point `API_BASE_URL` in `src/api/client.ts` at the real backend (or leave
   it empty for a same-origin deployment).
2. Stop starting the mock worker — delete or guard the `enableMocking()`
   call in `src/main.tsx` (it already only runs in dev builds via
   `import.meta.env.DEV`, so a production build already skips it).

Nothing else changes: every component only ever calls functions from
`api/client.ts`, which speak the exact request/response shapes documented
in DESIGN.md §6 regardless of who answers them.

## Project layout

See DESIGN.md §7 for the intended folder structure — `src/` follows it
directly. Every non-trivial file starts with a header comment explaining
what it does and, where relevant, which DESIGN.md section it implements.

## Known shortcuts (read before extending)

These are deliberate v1 simplifications, each with a comment at its call
site pointing back here. None of them are data-model compromises — they're
all in the "how it's rendered/wired today" category, safe to improve
incrementally without touching `api/types.ts` or DESIGN.md's contract.

- **Grounding evidence on the main map.** `GroundingEvidence` (bbox/point)
  is pixel-space relative to a patch's own raster — DESIGN.md's own note in
  §6.1. Today that's only rendered inside the Patch Viewer Drawer
  (`MaskOverlay`, via `lib/patchGeometry.ts`'s pixel→percent conversion). On
  the main MapLibre map, hovering a grounded span only highlights the whole
  footprint polygon (via the shared `hoveredPatchId`), not a precise
  in-patch box. Real georeferencing (projecting a patch's own pixel grid
  into lng/lat) would remove this gap — tracked, not required for v1.
- **Assumed patch pixel size.** `lib/patchGeometry.ts` assumes every patch
  is 120×120px (BigEarthNet's Sentinel-2 10m-band size) since evidence
  geometry doesn't carry its own dimensions yet. Update
  `ASSUMED_PATCH_PIXEL_SIZE` (or better, thread a real size through the API
  response) once real imagery/metadata is available.
- **In-drawer point-segment.** `PatchViewerDrawer`'s "Segment a region in
  this patch" sends the patch's centroid as the segmentation point rather
  than a true click-to-pixel-to-geo conversion off the preview `<img>`, and
  shows a text summary instead of a mask overlay (see the mask-overlay
  point above). Good enough to exercise the full endpoint → confirm → add
  pipeline; not pixel-accurate yet.
- **No toast/notification system.** A handful of failure paths (adding an
  incompatible context item, a failed upload) use `window.alert` rather
  than an inline or toast component. Fine for a working prototype; swap for
  a real notification component when one exists elsewhere in the app.
- **Mock query responses.** `mocks/mockQuery.ts` returns one canned answer
  per `ContextType`, not a real model. It exists purely so the chat UI,
  grounding highlights, execution trace, and report button all have
  something real to render end-to-end.
