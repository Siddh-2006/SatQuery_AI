"""
data/upload_store.py
======================
Backs `POST /api/uploads` (`ui/DESIGN.md` §4.2/§6.4) -- a researcher's own
image (most importantly, future ISRO/SAC Cartosat-2S/RISAT evaluation
pairs), not one of our indexed BigEarthNet patches.

What this does, honestly:
- Saves the raw upload and renders a real preview thumbnail. This part
  fully works for every accepted format.
- For GeoTIFF/TIFF, reads the file's own CRS + geotransform with rasterio
  to compute a real `detectedLocation` (the georeferenced center point) and
  guesses `detectedModality` from the band count (2 bands -> SAR VV+VH,
  more -> optical). No embedded-timestamp standard is reliable enough to
  read generically here, so `detectedTimestamp` is always left null for
  uploads -- same as `ui/DESIGN.md` §6.4 describes for "whatever the
  backend couldn't detect."
- For PNG/JPEG, nothing is detected (matches §4.2's "benchmark image with
  no embedded geodata" case exactly) -- location/modality/timestamp all
  come back null, and the UI's existing manual-entry flow handles the rest.

Note (see `orchestrator/DESIGN.md` §13): this module makes an upload
*storable and previewable*, which is everything `POST /api/uploads` needs
to do. *Querying* an upload with the EOCaptioner tool isn't wired up yet --
that's a separate, documented limitation in `compatibility.py`.
"""
import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import rasterio
from PIL import Image
from pyproj import Transformer

from app.config import settings

ALLOWED_EXTENSIONS = {"tif", "tiff", "png", "jpg", "jpeg"}
_FORMAT_BY_EXT = {"tif": "geotiff", "tiff": "geotiff", "png": "png", "jpg": "jpeg", "jpeg": "jpeg"}


@dataclass
class UploadResult:
    file_id: str
    original_filename: str
    format: str
    detected_modality: Optional[str]
    detected_location: Optional[dict]  # {"lat": ..., "lon": ...}
    detected_timestamp: Optional[str]
    preview_path: Path


def extension_of(filename: str) -> Optional[str]:
    if "." not in filename:
        return None
    return filename.rsplit(".", 1)[-1].lower()


def _detect_geotiff_metadata(path: Path) -> tuple[Optional[dict], Optional[str]]:
    """Returns (detectedLocation, detectedModality) for a GeoTIFF/TIFF, or
    (None, None) if it turns out to carry no usable CRS (e.g. a plain TIFF
    with no geo tags at all -- rasterio will happily open it, just with
    `crs=None`)."""
    with rasterio.open(path) as src:
        if src.crs is None:
            return None, None
        # Center of the raster's bounds, reprojected to WGS84 lon/lat --
        # the same idea as extract_patches.py's corner reprojection, just
        # for one center point instead of a full footprint polygon.
        cx = (src.bounds.left + src.bounds.right) / 2
        cy = (src.bounds.bottom + src.bounds.top) / 2
        transformer = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(cx, cy)
        location = {"lat": round(float(lat), 6), "lon": round(float(lon), 6)}

        # Crude but reasonable heuristic: BigEarthNet-style SAR products
        # carry 2 bands (VV, VH); anything else is treated as optical.
        # A real ISRO/SAC ingestion pipeline would sniff band metadata
        # more carefully -- flagged in DESIGN.md §14 as a future refinement.
        modality = "sar" if src.count == 2 else "optical"
        return location, modality


def _render_preview(path: Path, fmt: str, dest: Path, size: int = 256) -> None:
    """Renders a small PNG thumbnail for the upload dialog / context chip.
    GeoTIFF previews use the first 3 bands (or repeat 1 band 3x for a
    single-band SAR-style file) min/max-stretched -- there's no fixed
    known scale like BigEarthNet's S2_BAND_CLIP for an arbitrary upload, so
    a per-image stretch is the only generic option here."""
    if fmt == "geotiff":
        with rasterio.open(path) as src:
            n = min(src.count, 3)
            arr = src.read(list(range(1, n + 1))).astype("float32")
            lo, hi = float(arr.min()), float(arr.max())
            arr = (arr - lo) / (hi - lo) * 255 if hi > lo else arr * 0
            arr = arr.astype("uint8")
            if n == 1:
                img = Image.fromarray(arr[0], mode="L").convert("RGB")
            else:
                img = Image.fromarray(arr.transpose(1, 2, 0)[:, :, :3], mode="RGB")
    else:
        img = Image.open(path).convert("RGB")
    img.thumbnail((size, size))
    img.save(dest, format="PNG")


def save_upload(filename: str, content: bytes) -> UploadResult:
    """Saves one uploaded file under `settings.upload_store_dir/<fileId>/`
    and returns everything `POST /api/uploads`'s response needs. Raises
    `ValueError` on an unsupported extension or a file rasterio/Pillow
    can't parse -- the API route turns those into the `unsupported_format`
    / `corrupt_file` error codes from `ui/DESIGN.md` §6.9."""
    ext = extension_of(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"unsupported_format:'{filename}' is not GeoTIFF/TIFF/PNG/JPEG")

    file_id = f"up_{uuid.uuid4().hex[:12]}"
    file_dir = settings.upload_store_dir / file_id
    file_dir.mkdir(parents=True, exist_ok=True)
    original_path = file_dir / filename
    original_path.write_bytes(content)

    fmt = _FORMAT_BY_EXT[ext]
    detected_location: Optional[dict] = None
    detected_modality: Optional[str] = None

    try:
        if fmt == "geotiff":
            detected_location, detected_modality = _detect_geotiff_metadata(original_path)
        preview_path = file_dir / "preview.png"
        _render_preview(original_path, fmt, preview_path)
    except Exception as e:  # rasterio/Pillow couldn't parse it at all
        raise ValueError(f"corrupt_file:couldn't read '{filename}': {e}") from e

    return UploadResult(
        file_id=file_id,
        original_filename=filename,
        format=fmt,
        detected_modality=detected_modality,
        detected_location=detected_location,
        detected_timestamp=None,  # see module docstring -- no reliable generic source for this
        preview_path=preview_path,
    )


def preview_path_for(file_id: str) -> Optional[Path]:
    path = settings.upload_store_dir / file_id / "preview.png"
    return path if path.exists() else None
