# On-demand segmentation (SAM / MM-OVSeg) — PLACEHOLDER (model under development)

**Status: not ready.** Placeholder file, matching the shape of every
other specialist tool folder (see [`../README.md`](../README.md)). No
working backend exists yet, so this tool is not registered
(`orchestrator/tools/registry.py`) and `POST /api/segment` today always
returns a `segmentation_failed` error (`orchestrator/DESIGN.md` §4/§13).

## What this will eventually be

Per the SIH idea doc: given a point, box, or rough region the user
clicks/selects, produce a precise pixel-level mask of that object.
Candidates: SAM (Segment Anything Model, Kirillov et al. ICCV 2023) for
optical imagery, or MM-OVSeg (arXiv:2603.17528) for open-vocabulary
optical-SAR fusion segmentation.

## When this is ready, fill in below

- Exact input shape (point in lon/lat? pixel coords? optional
  `patchIdHint`? matches `ui/DESIGN.md` §6.3's `SegmentRequest`).
- Output shape (matches `SegmentResponse`: `geometry`, `resolvedPatchIds`,
  `confidence`, `modelUsed`).
- Any hard constraints.
- `capabilities.json` schema.

Ask to have this wired into `orchestrator/app/api/segment.py` (this one
isn't agent-tool-called like the others — it backs a direct UI action,
see `ui/DESIGN.md` §2.5 — so wiring it up mostly means replacing the
stub logic in that file with a real call to this model's backend).
