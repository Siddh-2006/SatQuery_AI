"""
data/geotiff_utils.py
=======================
Pure image I/O helpers for BigEarthNet-style per-band GeoTIFFs. Nothing in
this file runs a model -- it only reads/writes pixels. Two jobs:

1. `extract_patch_bands` -- pull just the band files one patch needs out of
   a `BigEarthNet-*.zip` archive into a plain folder on disk, so
   `server/serve.py` (the EOCaptioner model server) can read them the way
   it already expects (`<patch_id>_<band>.tif` files in a directory).
   Adapted directly from `server/serve.py`'s function of the same name.
2. `render_composite_png` -- render a human-viewable preview PNG (true
   color / false color / grayscale SAR) for `GET /api/patches/:id/preview`
   (`ui/DESIGN.md` §2.6/§6.6). The frontend never decodes GeoTIFF data
   itself -- this is the one place that happens.

Every function here is deliberately stateless (no caching, no globals) --
`patch_index.py` is the layer that decides *when* to call these and where
to cache the results.
"""
import io
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

# Same band lists / normalization constants server/serve.py uses, so a
# preview rendered here and a tensor loaded by the model agree on what
# "the image" looks like.
S2_BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]
S1_BANDS = ["VV", "VH"]
S2_BAND_CLIP = 4000.0
S1_DB_MIN, S1_DB_MAX = -25.0, 5.0


def extract_patch_bands(zip_path: Path, member_dir: str, patch_id: str, bands: list[str], dest_dir: Path) -> None:
    """Copies just `patch_id`'s band tifs out of `zip_path` into
    `dest_dir`, named `<patch_id>_<band>.tif` -- exactly what
    `server/serve.py`'s loader and the functions below expect. Skips any
    band file already present in `dest_dir`, so re-querying the same patch
    is instant instead of re-extracting from the zip every time."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for band in bands:
            filename = f"{patch_id}_{band}.tif"
            dest_file = dest_dir / filename
            if dest_file.exists():
                continue
            dest_file.write_bytes(zf.read(f"{member_dir}/{filename}"))


def _read_bands(folder: Path, patch_id: str, bands: list[str]) -> np.ndarray:
    """Reads each band's single-band GeoTIFF as a float32 array and stacks
    them into one (bands, H, W) array. Bands sometimes differ in native
    resolution (e.g. S2's 20m/60m bands vs its 10m bands) -- resized to
    match the largest band present so they stack cleanly."""
    arrs = []
    for band in bands:
        with rasterio.open(folder / f"{patch_id}_{band}.tif") as src:
            arrs.append(src.read(1).astype(np.float32))
    target_h = max(a.shape[0] for a in arrs)
    target_w = max(a.shape[1] for a in arrs)
    out = []
    for a in arrs:
        if a.shape != (target_h, target_w):
            # Nearest-neighbour resize via Pillow (already a dependency for
            # PNG encoding below) -- avoids pulling in torch/scipy just for
            # this rare "bands differ in native resolution" path. `mode="F"`
            # keeps the array as float32 through the resize.
            resized = Image.fromarray(a, mode="F").resize((target_w, target_h), resample=Image.NEAREST)
            a = np.array(resized)
        out.append(a)
    return np.stack(out, axis=0)


def render_composite_png(
    s2_dir: Path | None,
    s2_patch_id: str | None,
    composite: str,
    s1_dir: Path | None = None,
    s1_patch_id: str | None = None,
) -> bytes:
    """Renders one of the three composites `ui/DESIGN.md` §2.6 lists in its
    band-composite selector:

    - "true_color"  -> S2 bands B04/B03/B02 as R/G/B (needs s2).
    - "false_color" -> S2 bands B08/B04/B03 as R/G/B, the standard
                       vegetation-highlighting near-infrared composite
                       (needs s2).
    - "sar"         -> S1 VV band, grayscale, min/max stretched (needs s1).

    Raises FileNotFoundError (band tif missing) or ValueError (composite
    needs a modality that wasn't provided) -- callers turn those into a
    proper HTTP error.
    """
    if composite in ("true_color", "false_color"):
        if s2_dir is None or s2_patch_id is None:
            raise ValueError(f"composite '{composite}' needs optical (S2) bands, which this patch doesn't have")
        bands = ["B04", "B03", "B02"] if composite == "true_color" else ["B08", "B04", "B03"]
        r, g, b = _read_bands(s2_dir, s2_patch_id, bands)
        rgb = np.stack([r, g, b], axis=-1)
        rgb = np.clip(rgb, 0, S2_BAND_CLIP) / S2_BAND_CLIP
        rgb = (rgb * 255).astype(np.uint8)
        img = Image.fromarray(rgb, mode="RGB")
    elif composite == "sar":
        if s1_dir is None or s1_patch_id is None:
            raise ValueError("composite 'sar' needs SAR (S1) bands, which this patch doesn't have")
        (vv,) = _read_bands(s1_dir, s1_patch_id, ["VV"])
        vv = np.clip(vv, S1_DB_MIN, S1_DB_MAX)
        vv = (vv - S1_DB_MIN) / (S1_DB_MAX - S1_DB_MIN)
        gray = (vv * 255).astype(np.uint8)
        img = Image.fromarray(gray, mode="L")
    else:
        raise ValueError(f"unknown composite '{composite}' -- expected true_color, false_color, or sar")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
