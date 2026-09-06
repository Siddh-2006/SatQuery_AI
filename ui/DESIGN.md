# SatQuery AI — Frontend Design Document

**Status:** Draft v1 — agreed layout & data contracts, not yet built.
**Owner:** UI team. **Scope:** This document covers only the web frontend
(`ui/`). The orchestrator, specialist models, and all inference happen behind
the HTTP API defined in [Section 6](#6-api-contract-frontend--orchestrator).
The frontend never talks to models directly — it only ever talks to this API,
so the backend team can build the real orchestrator against this contract
independently, in parallel, without touching UI code.

**Stack decisions (locked in):**
- React + TypeScript, built with Vite.
- State: Zustand (small, no-boilerplate stores — see [Section 5](#5-state-management)).
- Map: MapLibre GL JS, basemap = Esri World Imagery (free, no API key).
- Styling: Tailwind CSS + a small shared token file for grounding colors /
  confidence scale, so visuals stay consistent across components.
- Mocking: Mock Service Worker (MSW) — intercepts `fetch` in the browser so
  the whole app runs and demos correctly with zero backend running, using
  fixture data in `src/mocks/`. Swapping in the real orchestrator later is a
  one-line change (disable MSW, point `API_BASE_URL` at it).
- Geometry: Turf.js — used client-side only to test whether a free-drawn
  polygon overlaps known patch footprints (see [2.4](#24-tool-free-draw));
  never used to interpret actual imagery.

Why this matters for the team: nobody has to wait on the orchestrator to
build or demo the UI, and nobody building the orchestrator has to guess what
JSON shape the frontend wants — it's specified once, here, and both sides
code against it.

---

## Table of contents
1. [Layout overview](#1-layout-overview)
2. [Center panel — map & patches](#2-center-panel--map--patches)
3. [Right panel — chat / prompt](#3-right-panel--chat--prompt)
4. [Left panel — context & temporal analysis](#4-left-panel--context--temporal-analysis)
5. [State management](#5-state-management)
6. [API contract (frontend ↔ orchestrator)](#6-api-contract-frontend--orchestrator)
7. [Folder structure](#7-folder-structure)
8. [Sessions — new / continue / load](#8-sessions--new--continue--load)
9. [Open items / future work](#9-open-items--future-work)

---

## 1. Layout overview

Three panels + a slim top bar, modelled on NotebookLM: any side panel can
collapse to an icon rail, the center panel always fills whatever space is
freed up.

```
┌─────────────────────────────────────────────────────────────────────┐
│ TOP BAR: [SatQuery AI] [Session: Untitled ▾][+New] [Basemap▾][Res▾]  │
├───────────┬─────────────────────────────────────┬───────────────────┤
│  LEFT     │  [🖱 Footprint][✏ Free draw][📍 Point]│   RIGHT           │
│  PANEL    │        ↑ selection toolbar           │   PANEL           │
│  (◀ coll- │        (map + patch footprints)     │   (chat / prompt) │
│  apsible) │                                     │   (coll. ▶)       │
│           │                                     │                   │
│ Context   │   [patch popover on click]          │  ┌ user msg ─┐    │
│ [+Upload] │                                     │  └───────────┘    │
│  (chips:  │   [slide-over Patch Viewer Drawer   │  ┌ assistant ─┐   │
│ 🖱/✏/📍/⬆)│    opens over this pane, right side]│  │ grounded   │   │
│ Temporal  │                                     │  │ text + evi-│   │
│  groups   │                                     │  │ dence      │   │
│           │                                     │  │ [trace ▾]  │   │
│ Time      │                                     │  │ [report ⬇] │   │
│  filter   │                                     │  └────────────┘   │
│           │                                     │                   │
│ Quick     │                                     │  [Grounding: ▾]   │
│  questions│                                     │  [ prompt box  ]  │
└───────────┴─────────────────────────────────────┴───────────────────┘
```

Rules:
- Each side panel has a small collapse chevron in its header; collapsed
  state persists per-browser via `localStorage` (not per-user account —
  there's no login in this prototype).
- Collapsing a panel doesn't destroy its state — the context set and the
  chat thread stay alive underneath, you're just hiding the view.
- Center panel never collapses; it just grows/shrinks as the sides do.
- The Patch Viewer is a **slide-over drawer** anchored to the right edge of
  the center panel (see [Section 2.6](#26-patch-viewer-drawer)) — it overlaps
  the map rather than replacing it, so the researcher can still see patch
  footprints while inspecting bands.
- The top bar carries the **session switcher** (current session name, "New
  session", "Load session ▾") — see [Section 8](#8-sessions--new--continue--load).

---

## 2. Center panel — map & patches

### 2.1 Two independent layers (important — do not conflate these)

The PS sources dataset imagery (Sentinel-1/2, via BigEarthNet) which is
lower-resolution and cannot be rendered directly as web map tiles without
server-side processing. The map's visual basemap is a **different, unrelated
image source** used purely for orientation. Concretely:

| Layer | Source | Purpose |
|---|---|---|
| Basemap | Esri World Imagery tile service | Visual reference only — lets the user recognize the terrain/place. **Never** read pixel data from this layer. |
| Patch footprints | Our own patch index (GeoJSON polygons, served by the backend) | The actual selectable dataset — each polygon carries a `patchId` that resolves to real S1/S2 files server-side. |

Clicking a footprint always resolves to a `patchId`, never to basemap
coordinates. The two layers can visually disagree (basemap shows today's
imagery, patch shows a 2020 Sentinel capture) — that's expected and fine.

**Implementation note — footprints are NOT a MapLibre GL layer.**
`PatchFootprintLayer` draws them itself: a plain `<canvas>` stacked over the
map via CSS (not MapLibre's style/source system), redrawn on every
pan/zoom by projecting each patch's real polygon through `map.project()`
and stroking it; hover/click hit-testing is done by hand with Turf's
`booleanPointInPolygon` against the cursor's `lngLat`. This is a deliberate
workaround, not a stylistic choice: maplibre-gl 4.7.1 (the version this app
is pinned to) never resolves `map.on("idle")` and renders zero features on
a GeoJSON source whenever any feature carries an `id`/`promoteId` — a real
upstream bug, fixed only in 5.21.1+. Footprint hover/"in context" styling
needs per-feature state, which needs an id, so a native GL layer is off the
table on the pinned version. Revisit this the day maplibre-gl is upgraded
past 5.21.1 — the native layer approach (GeoJSON source + fill/line/symbol
layers + `setFeatureState`) is simpler and should be preferred once the bug
isn't in the way.

Hover shows a small read-only tooltip (patchId, label, modalities, capture
dates, lat/lon) that follows the cursor — separate from, and lighter than,
the click popover in [2.3](#23-tool-footprint-select), which stays
click-only since it carries the "add to context" actions.

### 2.2 Area-of-interest selection toolbar

There are three distinct ways to tell the app "this is the area I'm asking
about," and the user picks one explicitly from a small toolbar docked at the
top of the center pane — like a tool selector in a drawing app, mutually
exclusive, current tool always visible:

| Tool | Icon | What it does |
|---|---|---|
| **Footprint select** (default) | 🖱 | Click a preregistered patch outline, shown over the RGB basemap with translucent fill so the boundary is visible without hiding the imagery underneath. See [2.3](#23-tool-footprint-select). |
| **Free draw** | ✏ | User draws an arbitrary polygon by hand. See [2.4](#24-tool-free-draw). |
| **Point segment** | 📍 | User clicks a single point; the backend's segmentation model grows it into a mask. See [2.5](#25-tool-point-segment). |

All three ultimately produce the same thing — a candidate addition to the
active context set — but they differ in exactly *what* gets sent to the
orchestrator, which is why each needs its own data shape
(see [ContextItem](#61-shared-data-model) in the API contract). Whichever
tool is active, the pending shape is drawn **dashed** on the map until the
user explicitly confirms "Add to context" (or presses Escape / clicks
Cancel to discard it) — nothing is added silently, so an accidental click
never pollutes the context.

### 2.3 Tool: footprint select

Click on a preregistered patch outline opens a small popover (not an
instant add — avoids overloading one click with two meanings):

```
┌ Patch LUX-0417 ───────────────┐
│ Luxembourg City area           │
│ Captured: 2021-06-14           │
│ Available: S2 (optical), S1(SAR)│
│                                 │
│ [ Add (default RGB) ]          │
│ [ Add SAR only ]                │
│ [ Add full S1+S2 bands ]        │
│ [ Inspect ▸ ]  (opens drawer)  │
└─────────────────────────────────┘
```

- "Add (default RGB)" / "Add SAR only" / "Add full bands" all add the patch
  to the active context set with a `bandSelection` (see data model in
  [Section 6.1](#61-shared-data-model)) — this is how the researcher focuses
  the orchestrator on exactly the data they want without re-uploading
  anything. This always resolves to exactly **one** patch.
- "Inspect" opens the Patch Viewer Drawer without touching context.
- Hovering a footprint that's already in the active context set highlights
  it (and its context chip in the left panel glows in sync — same
  hover-link mechanism used for grounding, see [3.2](#32-grounding-links-answer--visuals)).

### 2.4 Tool: free draw

The user draws a polygon directly on the basemap (click to place vertices,
double-click/Enter to close it). No backend call is needed to produce the
shape — it's exact, user-authored geometry. Before it can be added to
context the frontend must figure out **which known patches it overlaps**,
since a hand-drawn shape can easily cross patch boundaries:

- Computed client-side with Turf.js (`booleanIntersects` against the
  already-loaded footprint layer from [Section 2.1](#21-two-independent-layers-important--do-not-conflate-these))
  — no extra network round-trip needed just to know which patches are
  touched.
- The confirmation step (see [4.3](#43-area-selections-inside-context))
  shows the resulting patch count before the user commits, purely as
  information (e.g. "This shape overlaps 3 patches") — it's sent to the
  backend as `patchCount`/`resolvedPatchIds` either way; the UI doesn't warn
  or gate on it.
- A sane vertex/area cap (e.g. reject shapes bigger than N km² or with more
  than ~50 vertices) prevents someone from accidentally selecting half the
  map — exact limits to be tuned once the orchestrator team gives real
  numbers (tracked in [Section 9](#9-open-items--future-work)). This is
  purely a "did you mean to draw that" sanity check, unrelated to how many
  patches it resolves to.

### 2.5 Tool: point segment

The user clicks a single point on the map (or inside the Patch Viewer). The
frontend sends that point to the backend's on-demand segmentation model
(SAM / MM-OVSeg — the same specialist registry entry used to produce mask
*evidence* on answers, see [3.2](#32-grounding-links-answer--visuals)) via
`POST /api/segment` ([Section 6.3](#63-post-apisegment)) and receives back a
mask polygon, the patch(es) it touches, and a confidence score.

- The returned mask is drawn **dashed/translucent** as a pending selection,
  labeled with its confidence (e.g. "mask confidence: 89%") — the user
  confirms "Add to context" or discards and tries a different point. Never
  auto-added, since automatic segmentation can be wrong and the user needs a
  chance to reject a bad guess.
- Like free draw, the response carries `resolvedPatchIds` (the backend
  determines these, not the frontend — it knows the raster grid, the
  frontend only knows footprint polygons) and `patchCount`, shown the same
  way before confirmation.

### 2.6 Patch viewer drawer

Slide-over panel, right-anchored over the map, opened via "Inspect" or by
clicking a context chip in the left panel. Shows:
- Band-composite selector (True color / False color / SAR grayscale) —
  these are pre-rendered previews served by the backend
  (`GET /patches/:id/preview`), never computed client-side.
- Basic metadata: location, timestamp, sensor, resolution, available bands.
- An "Add to context" control mirroring the popover, for when the drawer was
  opened without adding first.
- The point-segment tool ([2.5](#25-tool-point-segment)) also works inside
  this drawer, for segmenting a region within one already-inspected patch.

### 2.7 Resolution / basemap control (top bar)

Dropdown to switch basemap style (e.g. imagery vs. a plain street map for
orientation) and to zoom to preset resolution levels. This only affects the
basemap layer, never the patch data.

---

## 3. Right panel — chat / prompt

### 3.1 Structure

Top-to-bottom: scrollable message thread, then a fixed footer with the
grounding-mode dropdown and the prompt input.

```
┌ Assistant ──────────────────────────────┐
│ The [built-up area]¹ has increased      │
│ along the [river corridor]².            │
│                                          │
│ Confidence: ▓▓▓▓▓▓▓░░░ 74%              │
│ [▾ Execution trace]   [⬇ Download report]│
└──────────────────────────────────────────┘
```
`¹` `²` = colored highlighted spans, each tied to one evidence item.

### 3.2 Grounding links answer ↔ visuals

Every grounded span in the answer text and its corresponding overlay
(bounding box / mask, drawn either on the map or in the Patch Viewer Drawer
depending on which patch it belongs to) share one `evidenceId` and one
color. Hover either side, the other highlights. This is the single most
important interaction in the app — it's the whole point of "grounding" — so
it's implemented once, centrally, in the state layer
([Section 5](#5-state-management)), not duplicated per component.

### 3.3 Grounding-mode dropdown

A small control near the prompt box lets the user request a preferred
output modality from the orchestrator for the *next* message — e.g.
"Bounding box", "Segmentation mask", "Auto (let orchestrator decide)". This
is sent as `groundingPreference` in the query request
([Section 6.2](#62-post-apiquery)); the orchestrator is free to ignore it if
the selected specialist model can't produce that form, in which case the
response simply says which form it actually returned.

### 3.4 Execution trace & report (mandatory PS deliverable)

Per the problem statement, every answer must expose an auditable execution
summary and be downloadable. Each assistant message has:
- A collapsed-by-default **"Execution trace"** accordion showing the task
  the orchestrator classified the query as, the model(s)/tool(s) it ran, and
  the key parameters used — straight from `executionTrace` in the API
  response, rendered as-is, no client-side interpretation.
- A **"Download report"** button that fetches `reportUrl` (a PDF or JSON
  produced server-side) — the frontend does not generate reports itself.

### 3.5 Prompt input

Standard multiline text box + send button. Submitting always attaches the
**currently active context set** (see [Section 4](#4-left-panel--context--temporal-analysis))
to the request. If no context set is active, the input is disabled with a
hint ("Select a patch on the map to begin") — the PS has no "no image"
query mode, so we shouldn't pretend one exists.

---

## 4. Left panel — context & temporal analysis

### 4.1 Context sets, typed to match the PS exactly

Rather than a freeform bag of patches, context is modeled as one of exactly
three types — the same three the PS defines as valid inputs. This keeps the
UI from ever assembling a request the orchestrator can't fulfill:

| Context type | Items | Typical use |
|---|---|---|
| `single` | 1 item — whole patch, an area selection, **or an uploaded image** | VQA, captioning, grounding, on-demand segmentation |
| `cross_modal_pair` | 2 items, both S1 (SAR) + S2 (optical) bands present between them, **same location** — whole patches and/or uploaded images | Optical–SAR fusion questions |
| `bitemporal_pair` | 2 items, **same location**, different timestamps — whole patches and/or uploaded images | Change detection / change-VQA |

Each item comes from one of three sources: the map
([Section 2](#2-center-panel--map--patches), producing a whole `PatchRef` or
an `AreaSelectionRef`), or a direct upload
([4.2](#42-uploading-your-own-imagery), producing an `UploadedImageRef`).
An upload and a map patch can freely sit in the same pair — the orchestrator
only cares that both items are georeferenced and, for `bitemporal_pair`,
share a location.

**v1 restriction:** area selections (free draw / point segment) may only go
into a `single` context set. Cross-modal and bitemporal analysis require
whole, unambiguous images — matching a hand-drawn shape across two
timestamps, or splitting it across both modalities, is real future
functionality but adds fragility we don't need for the first version
(tracked in [Section 9](#9-open-items--future-work)). Uploaded images are
**not** under this restriction — see [4.2](#42-uploading-your-own-imagery)
for why an upload's own location data decides what it can be paired with.

The left panel shows the active context set as a card with removable chips,
and a dropdown/list of any other saved context sets to switch between (so a
researcher can prep a bitemporal set and a single-patch set side by side
without losing either).

Guardrail: adding a second patch to a set only offers "bitemporal pair" as
an option when the two patches share a location; otherwise the UI blocks it
with an explanation, rather than silently building a meaningless request.
This directly solves the ambiguity you flagged — a user physically cannot
submit "temporal analysis" on two unrelated places.

### 4.2 Uploading your own imagery

The map only knows about patches already in our indexed dataset. The PS
also requires accepting a researcher's own image directly — most notably
the ISRO/SAC evaluation pairs (Cartosat-2S optical + RISAT SAR), which
won't be pre-indexed the way BigEarthNet patches are. Upload is a separate
entry point from the map tools in [Section 2](#2-center-panel--map--patches)
— it lives as an **"Upload image" button at the top of the Context Manager
card** in this left panel, since it builds a context item without touching
the map at all.

Flow:
1. Click "Upload image" → a small dialog opens with a drag-and-drop
   dropzone (accepts `.tif`/`.tiff`; `.png`/`.jpg` accepted too, restricted
   to the prescribed public benchmark datasets per the PS — the dialog says
   so, but the authoritative check is server-side).
2. The file is sent immediately to `POST /api/uploads`
   ([Section 6.4](#64-post-apiuploads)) with a progress bar. The backend
   extracts what metadata it can — location and timestamp from GeoTIFF
   tags, modality from the file's bands — and returns an `UploadedImageRef`
   plus a rendered preview thumbnail (same idea as a patch preview).
3. The result appears as a **pending card** (dashed, same visual language as
   every other pending selection in this app — [2.2](#22-area-of-interest-selection-toolbar)),
   showing the thumbnail and whatever metadata was detected. Anything the
   backend couldn't detect — most likely modality or a usable timestamp for
   a benchmark PNG/JPEG with no embedded geodata — is left for the
   researcher to fill in manually before it can be added.
4. "Add to context" commits it as an `UploadedImageRef` item, exactly like
   confirming a map selection. It gets its own icon (⬆) in the context chip
   list next to 🖱/✏/📍 ([4.3](#43-area-selections-inside-context)).

An upload with no detected location (an un-georeferenced benchmark image)
can only ever be used in a `single` context set, because `cross_modal_pair`
and `bitemporal_pair` both require matching items by location — this falls
out of the existing validation rules naturally rather than needing a
separate special case. An upload *with* a location behaves exactly like a
`PatchRef` for pairing purposes.

### 4.3 Area selections inside context

Free-draw and point-segment items need a bit more care in the context list
than a plain patch chip, because a researcher must be able to tell at a
glance *what a chip actually is* and undo an accidental one:

- Every chip shows a small icon for how it was created — 🖱 footprint,
  ✏ free draw, 📍 point segment — plus a thumbnail crop of the selected
  area, so "what is this" is answerable without opening anything.
- If the item's `resolvedPatchIds` has more than one entry, the chip shows a
  plain **"N patches"** count next to the icon — informational only, no
  warning styling, no UI gating on the number. The frontend's only job here
  is to make sure that count is correct and visible.
- `patchCount` / `resolvedPatchIds` are sent as first-class fields in the
  API payload ([Section 6.1](#61-shared-data-model)), never inferred by the
  backend after the fact, so the orchestrator always knows how many patches
  a selection touches and can handle that however it needs to (split the
  work, cap it, reject it, whatever) — that decision is entirely a backend
  concern, not something the frontend tries to anticipate.
- Hovering a chip highlights its actual drawn/segmented shape on the map or
  drawer (same shared hover-link mechanism as footprints and grounding
  evidence, see [3.2](#32-grounding-links-answer--visuals)) — so identifying
  and removing something added by mistake never requires guessing.
- Mask-shaped evidence on chat answers ([3.2](#32-grounding-links-answer--visuals))
  and mask-shaped area selections here are rendered by the same
  `MaskOverlay` component — one visual language for "a model outlined this
  region," whether it's output (grounding) or input (context selection).

### 4.4 Temporal browser

A location-grouped list: pick a location (from a footprint already added,
or from the map), see every timestamp we have data for at that place.
Each timestamp row has:
- **View** — opens that patch alone in the Patch Viewer Drawer, read-only,
  no context change.
- **Add to temporal set** — adds it into a `bitemporal_pair` context set
  (disabled once two are already picked; swap requires removing one first).

A date-range filter narrows the timestamp list for locations with many
captures.

### 4.5 Quick questions (FAQ)

A short list of one-click example queries (LULC summary, vegetation
health, "what changed between these two dates", "fuse optical+SAR for
built-up area") that fill the prompt box and submit immediately. The list
is **context-aware**: bitemporal questions only appear when a
`bitemporal_pair` set is active, fusion questions only when a
`cross_modal_pair` set is active, etc. — steering users toward queries the
current context can actually answer.

---

## 5. State management

Four small Zustand stores, kept deliberately separate so each is easy to
read in isolation:

- **`useMapStore`** — footprints loaded, hovered/selected patchId, drawer
  open/closed + which patch it shows, the **active selection tool**
  (`"footprint" | "free_draw" | "point_segment"`, [2.2](#22-area-of-interest-selection-toolbar)),
  and the current **pending selection** (the dashed, not-yet-confirmed
  shape/point/mask a tool is mid-way through) — cleared on confirm, cancel,
  or Escape.
- **`useContextStore`** — all context sets, which one is active, guardrail
  logic from [4.1](#41-context-sets-typed-to-match-the-ps-exactly)/[4.3](#43-area-selections-inside-context),
  and any in-progress upload (file + progress + detected/pending metadata,
  [4.2](#42-uploading-your-own-imagery)) until it's confirmed into an item
  or discarded.
- **`useChatStore`** — message list per context set, in-flight request
  state, and the shared `hoveredEvidenceId` that powers the answer↔visual
  hover-link from [3.2](#32-grounding-links-answer--visuals) (both the chat
  components and the map/drawer components subscribe to this one value —
  the same mechanism also carries `hoveredContextItemId` for the chip
  hover-link in [4.3](#43-area-selections-inside-context), so there's one
  hover-highlight primitive in the whole app, not several copies of the
  same idea).
- **`useSessionStore`** — current `sessionId` + title, and the list of past
  sessions for the switcher (see [Section 8](#8-sessions--new--continue--load)).
  Owns the "new session" / "load session" actions, which reset or hydrate
  `useContextStore` and `useChatStore` together.

No global "app state" blob — components import only the store(s) they need.

---

## 6. API contract (frontend ↔ orchestrator)

All requests go through `src/api/client.ts`. In development, MSW intercepts
these and answers from `src/mocks/fixtures/*.json`, so the shapes below are
enforced by TypeScript types shared between the mock handlers and the real
client — the mock can't drift from the contract silently.

**Quick reference.** Two tables: what the frontend *sends* (outgoing) and
what it *receives back* (incoming) for each endpoint, in short — click the
"Detail" link for the full request/response shape.

**Outgoing — requests the frontend sends**

| Endpoint | Method | Sent when | Key data sent | Detail |
|---|---|---|---|---|
| `/api/query` | POST | User submits a prompt | `sessionId`, `query` text, typed `contextSet` (patches, area selections, and/or uploaded images), `groundingPreference` | [§6.2](#62-post-apiquery) |
| `/api/segment` | POST | Point-segment tool clicked | `point {lat, lon}`, optional `patchIdHint` | [§6.3](#63-post-apisegment) |
| `/api/uploads` | POST | "Upload image" file selected | one image file (`multipart/form-data`) | [§6.4](#64-post-apiuploads) |
| `/api/patches` | GET | Map viewport loads/changes | `bbox` | [§6.5](#65-get-apipatchesbboxminlonminlatmaxlonmaxlat) |
| `/api/patches/:id/preview` | GET | "Inspect" / drawer opened | `patchId`, `composite` type | [§6.6](#66-get-apipatchespatchidpreviewcompositetruecolorfalsecolorsar) |
| `/api/patches/:id/timeseries` | GET | Temporal browser opened for a location | `patchId` | [§6.7](#67-get-apipatchespatchidtimeseries) |
| `/api/reports/:id` | GET | "Download report" clicked | `reportId` | [§6.8](#68-get-apireportsreportid) |
| `/api/sessions` | GET | Session switcher opened | — | [§8](#8-sessions--new--continue--load) |
| `/api/sessions/:id` | GET | "Load session" picked | `sessionId` | [§8](#8-sessions--new--continue--load) |
| `/api/sessions` | POST | "New session" clicked | — (empty body) | [§8](#8-sessions--new--continue--load) |

**Incoming — what the frontend receives back**

| Endpoint | Returns | Key data received | Detail |
|---|---|---|---|
| `/api/query` response | A grounded answer | `answer` text, `groundedSpans[]`, `evidence[]` (bbox/mask/point), `confidence`, `executionTrace`, `reportUrl` | [§6.2](#62-post-apiquery) |
| `/api/segment` response | One segmentation mask | `geometry`, `resolvedPatchIds[]`, `confidence`, `modelUsed` | [§6.3](#63-post-apisegment) |
| `/api/uploads` response | One uploaded image's metadata | `fileId`, `format`, detected modality/location/timestamp (nullable), `previewUrl` | [§6.4](#64-post-apiuploads) |
| `/api/patches` response | Patch footprints | GeoJSON `FeatureCollection` (`patchId`, location, `availableTimestamps[]`, modalities per feature) | [§6.5](#65-get-apipatchesbboxminlonminlatmaxlonmaxlat) |
| `/api/patches/:id/preview` response | A rendered composite image | PNG binary | [§6.6](#66-get-apipatchespatchidpreviewcompositetruecolorfalsecolorsar) |
| `/api/patches/:id/timeseries` response | Sibling captures at that location | `{ patchId, timestamp, thumbnailUrl }[]` | [§6.7](#67-get-apipatchespatchidtimeseries) |
| `/api/reports/:id` response | Downloadable file | PDF/JSON binary stream | [§6.8](#68-get-apireportsreportid) |
| `/api/sessions` response | Past sessions list | `SessionSummary[]` | [§8](#8-sessions--new--continue--load) |
| `/api/sessions/:id` response | One session's full state | `SessionDetail` (`contextSets[]`, `messages[]`) | [§8](#8-sessions--new--continue--load) |
| `/api/sessions` POST response | New session id | `{ id: string }` | [§8](#8-sessions--new--continue--load) |
| *(any endpoint, on failure)* | An error, instead of the above | `{ error: { code, message, details? } }` | [§6.9](#69-error-responses) |

### 6.1 Shared data model

```ts
type Modality = "optical" | "sar";
type BandSelection = "default_rgb" | "sar_only" | "full_bands";
type ContextType = "single" | "cross_modal_pair" | "bitemporal_pair";
type SelectionMethod = "footprint" | "free_draw" | "point_segment";

// A whole, unambiguous dataset patch — used by all three context types.
interface PatchRef {
  kind: "patch";
  patchId: string;          // stable id in our patch index, e.g. "LUX-0417"
  lat: number;
  lon: number;
  timestamp: string;        // ISO 8601 capture date
  availableModalities: Modality[];
  bandSelection: BandSelection;
}

// A user-drawn or model-segmented sub-region — "single" context type only
// (see 4.1). May span more than one underlying patch, which is exactly why
// resolvedPatchIds/patchCount are explicit, first-class fields: the
// orchestrator must know this up front, not discover it mid-inference.
interface AreaSelectionRef {
  kind: "area_selection";
  method: Extract<SelectionMethod, "free_draw" | "point_segment">;
  geometry: GeoJSON.Polygon | GeoJSON.Point; // exact for free_draw, mask outline for point_segment
  resolvedPatchIds: string[];   // every patch this selection overlaps
  patchCount: number;           // = resolvedPatchIds.length, kept explicit for convenience
  segmentationConfidence?: number; // present only for method "point_segment"
}

// A researcher-supplied image (GeoTIFF/TIFF, or PNG/JPEG for benchmark
// datasets) that isn't in our indexed patch footprints — see 4.2. Usable in
// any context type; location/timestamp are null when the backend couldn't
// detect them (e.g. a non-georeferenced benchmark PNG), which naturally
// limits such an item to a "single" context set via the same location-
// matching rules used for pairing patches.
interface UploadedImageRef {
  kind: "uploaded_image";
  fileId: string;             // id returned by POST /api/uploads
  originalFilename: string;
  format: "geotiff" | "tiff" | "png" | "jpeg";
  detectedModality: Modality | null;
  detectedLocation: { lat: number; lon: number } | null;
  detectedTimestamp: string | null;
  previewUrl: string;         // server-rendered thumbnail
}

type ContextItem = PatchRef | AreaSelectionRef | UploadedImageRef;

interface ContextSet {
  id: string;
  type: ContextType;
  items: ContextItem[];     // length 1 for "single"; length 2 (patch and/or
                             // uploaded_image, sharing a location) for both pair types
}

interface GroundingEvidence {
  id: string;
  patchId: string;          // which patch this overlay belongs to
  kind: "bbox" | "mask" | "point";
  // bbox: [xMin, yMin, xMax, yMax] in the patch's pixel space
  // mask: URL to a PNG mask aligned to the patch preview image
  // point: [x, y]
  geometry: number[] | string;
  label: string;
}

interface ExecutionTrace {
  task: string;                                   // e.g. "change_vqa"
  modelsUsed: { name: string; role: string }[];    // e.g. {name:"ChangeChat", role:"change_understanding"}
  parameters: Record<string, unknown>;
}
```

### 6.2 `POST /api/query`

Request:
```json
{
  "sessionId": "sess_9f2a",
  "query": "Has the built-up area increased, decreased, or remained unchanged?",
  "contextSet": {
    "id": "ctx_1",
    "type": "bitemporal_pair",
    "items": [
      { "kind": "patch", "patchId": "LUX-0417", "lat": 49.61, "lon": 6.13, "timestamp": "2019-05-02", "availableModalities": ["optical","sar"], "bandSelection": "default_rgb" },
      { "kind": "patch", "patchId": "LUX-0417", "lat": 49.61, "lon": 6.13, "timestamp": "2023-07-19", "availableModalities": ["optical","sar"], "bandSelection": "default_rgb" }
    ]
  },
  "groundingPreference": "auto"
}
```

An area-selection `single` request looks like this instead (note the item
`kind` and the explicit patch count):
```json
{
  "sessionId": "sess_9f2a",
  "query": "What is growing in this field?",
  "contextSet": {
    "id": "ctx_2",
    "type": "single",
    "items": [
      {
        "kind": "area_selection",
        "method": "point_segment",
        "geometry": { "type": "Polygon", "coordinates": [[ /* mask outline */ ]] },
        "resolvedPatchIds": ["LUX-0417", "LUX-0418"],
        "patchCount": 2,
        "segmentationConfidence": 0.89
      }
    ]
  },
  "groundingPreference": "auto"
}
```

Response:
```json
{
  "answer": "The built-up area has increased, concentrated along the river corridor.",
  "groundedSpans": [
    { "start": 4, "end": 20, "evidenceId": "ev_1" }
  ],
  "evidence": [
    { "id": "ev_1", "patchId": "LUX-0417", "kind": "mask", "geometry": "https://.../ev_1_mask.png", "label": "increased built-up area" }
  ],
  "confidence": 0.74,
  "executionTrace": {
    "task": "change_vqa",
    "modelsUsed": [{ "name": "ChangeChat", "role": "change_understanding" }],
    "parameters": { "threshold": 0.5 }
  },
  "reportUrl": "/api/reports/rep_abc123"
}
```

Validation the frontend performs before sending (fast local feedback,
mirrors — but does not replace — server-side validation):
- `contextSet.items.length` matches what `type` requires.
- `bitemporal_pair` and `cross_modal_pair` items are `kind: "patch"` or
  `kind: "uploaded_image"` only — `area_selection` items are rejected
  client-side outside `single` sets (v1 restriction,
  [4.1](#41-context-sets-typed-to-match-the-ps-exactly)).
- An `uploaded_image` item with `detectedLocation: null` is rejected
  client-side outside `single` sets — there's no location to match it by.
- `bitemporal_pair` items share a location (`lat`/`lon` for patches,
  `detectedLocation` for uploads).
- `cross_modal_pair` requires both S1 (SAR) and S2 (optical) covered across
  its items (`bandSelection`/`availableModalities` for patches,
  `detectedModality` for uploads).

### 6.3 `POST /api/segment`

Backs the point-segment tool ([2.5](#25-tool-point-segment)). Request:
```json
{ "point": { "lat": 49.612, "lon": 6.131 }, "patchIdHint": "LUX-0417" }
```
Response:
```json
{
  "geometry": { "type": "Polygon", "coordinates": [[ /* mask outline */ ]] },
  "resolvedPatchIds": ["LUX-0417"],
  "confidence": 0.89,
  "modelUsed": "SAM"
}
```
`patchIdHint` is optional — set when the click happened inside the Patch
Viewer Drawer for a known patch; omitted for a raw map click, where the
backend must resolve location purely from the point. The frontend never
calls this for free-draw shapes — those need no model, the drawn polygon
*is* the geometry.

### 6.4 `POST /api/uploads`

Backs the upload flow ([4.2](#42-uploading-your-own-imagery)). One file per
call, `multipart/form-data`:

Request: a single file field (`.tif`/`.tiff`/`.png`/`.jpg`).

Response:
```json
{
  "fileId": "up_7f3d",
  "originalFilename": "cartosat_scene_014.tif",
  "format": "geotiff",
  "detectedModality": "optical",
  "detectedLocation": { "lat": 28.61, "lon": 77.21 },
  "detectedTimestamp": "2024-03-11",
  "previewUrl": "https://.../up_7f3d_preview.png"
}
```
Any of `detectedModality`, `detectedLocation`, `detectedTimestamp` may come
back `null` when the file carries no usable metadata (typically a benchmark
PNG/JPEG) — the upload dialog then asks the researcher to fill in what's
missing (at minimum modality, for pairing purposes) before "Add to context"
is enabled. Format/corruption/size problems come back as a normal error
response ([6.9](#69-error-responses)), not a 200 with nulls.

### 6.5 `GET /api/patches?bbox=<minLon,minLat,maxLon,maxLat>`

Returns a GeoJSON `FeatureCollection`; each feature's `properties` holds a
`PatchRef`-shaped object (minus `bandSelection`, which is a UI-only concept
added when the patch is added to context) plus `availableTimestamps: string[]`.

The mock behind this endpoint is backed by the **real** delivered dataset —
every Sentinel-1/Sentinel-2 patch BigEarthNet cut over Kosovo (UTM tile
34TEN, 1,616 patches) and Luxembourg (UTM tile 31UGR, 1,814 patches), each
with its true WGS84 footprint (reprojected from the source GeoTIFFs' own
geotransform, not approximated), real available modalities, and every real
capture date found in the archives — see
[`scripts/extract_patches.py`](#7-folder-structure) for how it's built, and
[Section 7](#7-folder-structure) for where the output lives. With both
regions' full grids in one fixture, the mock actually filters by `bbox` now
(matching what a real backend's spatial index would do) rather than always
returning everything — see `mocks/handlers.ts`.

### 6.6 `GET /api/patches/:patchId/preview?composite=true_color|false_color|sar`

Returns a rendered PNG for display in the Patch Viewer Drawer. The frontend
never decodes GeoTIFF/band data itself.

### 6.7 `GET /api/patches/:patchId/timeseries`

Returns every known capture at that patch's location, for the temporal
browser: `{ patchId, timestamp, thumbnailUrl }[]`.

### 6.8 `GET /api/reports/:reportId`

Streams the downloadable report file (PDF or JSON) referenced by
`reportUrl`.

### 6.9 Error responses

Every endpoint above returns this shape instead of its normal body on
failure (non-2xx status):

```json
{
  "error": {
    "code": "incompatible_context",
    "message": "Cross-modal analysis requires both SAR and optical bands on the same patch.",
    "details": { "patchId": "LUX-0417", "missingModality": "sar" }
  }
}
```

`code` is a stable machine-readable string the frontend can branch on (e.g.
to point the researcher back at the context panel); `message` is safe to
show to the user as-is. Known codes so far — the orchestrator team can add
more, the frontend just needs `code`/`message`/`details` to always be
present in that shape:

| Code | Meaning |
|---|---|
| `incompatible_context` | The context set doesn't satisfy what the query/task needs (e.g. missing a modality). |
| `unsupported_task` | The query couldn't be mapped to any specialist task the orchestrator knows. |
| `segmentation_failed` | `/api/segment` couldn't produce a mask for the given point. |
| `unsupported_format` | `/api/uploads` received a file type outside GeoTIFF/TIFF/PNG/JPEG, or a PNG/JPEG outside an approved benchmark dataset. |
| `corrupt_file` | `/api/uploads` couldn't parse the uploaded file at all. |
| `model_error` | A specialist model failed or timed out during execution. |

This also covers the PS's "compatibility checking" requirement — the
frontend does light client-side checks before sending
([§6.2 validation](#62-post-apiquery)), but the authoritative check happens
server-side and comes back through this same error shape, surfaced next to
the prompt input or the offending context chip rather than as a generic
failure toast.

---

## 7. Folder structure

```
ui/
  DESIGN.md                 ← this file
  scripts/
    extract_patches.py       Builds mocks/fixtures/real-patches/*.json from the
                              BigEarthNet-<Region>-S1/S2.zip archives — see its
                              own header comment for prerequisites/usage. Only
                              needs re-running if the source zips change; the
                              app itself just statically imports the JSON.
    requirements.txt          Python deps for the script above (rasterio, pyproj)
                              — unrelated to the frontend's own package.json.
  src/
    main.tsx
    App.tsx                 ← assembles TopBar + 3 panels
    components/
      layout/                AppShell, CollapsiblePanel, TopBar, SessionSwitcher
      map/                    MapView, PatchFootprintLayer (canvas overlay, not a
                               MapLibre layer — see 2.1), PatchPopover,
                               SelectionToolbar, FreeDrawTool, PointSegmentTool,
                               MaskOverlay (shared by grounding evidence & area selections)
      viewer/                 PatchViewerDrawer, BandCompositeSelector
      chat/                   ChatPanel, MessageBubble, GroundedText,
                               GroundingModeDropdown, ExecutionTraceAccordion,
                               ReportDownloadButton
      context/                ContextManagerPanel, ContextChip, UploadDialog,
                               TemporalBrowser, TimeRangeFilter
      faq/                    QuickQuestionsList
    state/                   useMapStore.ts, useContextStore.ts, useChatStore.ts,
                              useSessionStore.ts
    api/                     client.ts, types.ts (the Section 6 types, single source of truth)
    mocks/                   handlers.ts (MSW), fixtures/
                                patches.ts             assembles the FeatureCollection
                                real-patches/*.json     real Kosovo/Luxembourg patch data,
                                                         built by scripts/extract_patches.py
                                sessions.ts
    styles/                  tokens.css (grounding colors, confidence scale), tailwind.config
  public/
```

Every non-trivial file starts with a short header comment: what the file
does, what it depends on, what it deliberately does *not* do — so a
teammate can open any one file without reading the whole app first.

---

## 8. Sessions — new / continue / load

A session bundles one chat thread together with the context set(s) it was
built from, so conversation stays coherent turn-to-turn but a researcher can
also start over cleanly or come back to earlier work. Persistence itself is
entirely a backend concern (a database, not `localStorage`) — the frontend's
job is just the three actions below and the switcher UI in the top bar.

- **Continue (default state):** every message sent within a session keeps
  using `useContextStore`'s active context set unless the researcher changes
  it; each `POST /api/query` carries the current `sessionId` so the backend
  can append to that session's history itself — the frontend doesn't do any
  separate "save" step.
- **New session:** clears `useContextStore` and `useChatStore` (the old
  session's data is already persisted server-side, so nothing is lost) and
  calls `POST /api/sessions` for a fresh `sessionId`. This is the answer to
  "a new session must not carry the previous one's context."
- **Load session:** the switcher's dropdown lists past sessions
  (`GET /api/sessions`, newest first, titled by their first query). Picking
  one calls `GET /api/sessions/:id` and replaces the contents of both stores
  with what comes back — so the researcher sees exactly the context sets and
  chat history that session had.

Data shapes:
```ts
interface SessionSummary {
  id: string;
  title: string;          // derived server-side, e.g. from the first query
  createdAt: string;
  lastUpdatedAt: string;
}

interface SessionDetail extends SessionSummary {
  contextSets: ContextSet[];
  messages: ChatMessage[]; // see 3.1 — includes each message's confidence,
                            // executionTrace and reportUrl as originally returned
}
```
- `GET /api/sessions` → `SessionSummary[]`
- `GET /api/sessions/:id` → `SessionDetail`
- `POST /api/sessions` → `{ id: string }` (creates and returns a new empty session)

## 9. Open items / future work

- Real user auth — out of scope for the hackathon prototype; sessions are
  identified by id only, no login.
- Draggable panel widths (currently fixed presets + collapse only) — v2 if
  time allows.
- Server-side confirmation of the client-side context validation in
  [6.2](#62-post-apiquery) — the frontend check is a UX nicety, the real
  guardrail must live in the orchestrator.
- Multi-context comparison view (viewing two context sets' answers side by
  side) — not requested yet, noted here so it's not forgotten if asked for.
- Exact free-draw vertex/area sanity limits (max km², max vertices) —
  placeholder numbers only until the orchestrator team gives real
  thresholds ([2.4](#24-tool-free-draw)). Not related to `patchCount`
  handling, which the frontend always reports and never gates on — any
  limits on how many patches a selection may span are a backend/model
  decision, made from the `patchCount` the frontend already sends
  ([4.3](#43-area-selections-inside-context)).
- Bitemporal/cross-modal analysis over a hand-drawn area selection (rather
  than a whole patch) — deliberately out of v1 scope, see
  [4.1](#41-context-sets-typed-to-match-the-ps-exactly).
- Session rename/delete from the UI — v1 only needs create/list/load.
- Batch/multi-file upload (selecting several files at once with a combined
  progress view) — v1 is deliberately one file at a time
  ([4.2](#42-uploading-your-own-imagery)); revisit if uploading a whole
  bitemporal/cross-modal pair in one step turns out to matter for the demo.
- The manual-entry form for metadata an upload couldn't detect (modality
  picker, date input) is specified only at the level of "the researcher can
  fill it in" ([4.2](#42-uploading-your-own-imagery)) — exact field layout
  is a small enough component to design at build time rather than here.
