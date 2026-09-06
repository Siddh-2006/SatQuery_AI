"""
orchestrator/data
===================
Everything to do with turning a `patchId` into real pixels: finding which
BigEarthNet zip archive holds it, extracting just the band files that are
needed, and rendering preview composites. See `orchestrator/DESIGN.md` §6.

- `patch_index.py` -- the footprint index (reused from `ui/`'s fixtures)
  plus patchId -> zip member resolution.
- `geotiff_utils.py` -- band loading, extraction, and PNG rendering. No
  model code lives here -- this is pure image I/O, shared by the patch
  preview endpoint and by the EOCaptioner tool (which needs real folder
  paths to hand to `server/serve.py`).
- `upload_store.py` -- saving + inspecting researcher-uploaded images.
"""
