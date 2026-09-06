"""
Fully offline, self-contained inference server for EOCaptioner. No network
calls at runtime -- everything loads from a local `offline_model/` bundle
produced once by export_offline_model.py. This file has no dependency on
the training repo's `src/` package; it's a standalone deployable script.

Run:
    python serve.py --bundle offline_model --port 8000

Then open http://localhost:8000/ in a browser for a small built-in tester
UI (static/index.html) -- point it at a folder of `<patch_id>_B0x.tif`
files, it renders a true-color preview (GET /preview) and lets you send a
prompt against that same patch (POST /generate). No separate frontend
project/build step; it's one static HTML file FastAPI serves directly.

The UI's "matching pairs" dropdown picks a location that has BOTH a real
S1 and S2 capture (GET /pairs, built once by scripts/build_pair_index.py
from the BigEarthNet-*.zip archives) instead of you finding/typing a
matching folder pair by hand. Selecting one calls GET /pairs/resolve,
which lazily extracts just that pair's band files out of the zips into
.cache/ the first time it's picked (nothing is bulk-extracted up front)
and fills in the S2/S1 fields for you.

Query the API directly instead, if you prefer -- /generate streams the
answer as plain text, one token as soon as it's produced, so use --no-buffer
(or -N) to see it arrive incrementally instead of curl buffering it all up:
    curl -N -X POST http://localhost:8000/generate \
      -H "Content-Type: application/json" \
      -d '{
            "s2_dir": "/path/to/dataset/images/S2/<patch_id>",
            "patch_id": "<patch_id>",
            "prompt": "Describe the land cover in this image."
          }'
"""
import argparse
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from threading import Thread
from typing import Optional

import numpy as np
import rasterio
import torch
import torch.nn as nn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from PIL import Image
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

STATIC_DIR = Path(__file__).parent / "static"
PAIRS_PATH = STATIC_DIR / "pairs.json"
# Where GET /pairs/resolve lazily extracts a picked pair's band files to.
# Keyed by pair id, so re-picking the same pair later is a cache hit.
CACHE_DIR = Path(__file__).parent / ".cache"
# Where scripts/build_pair_index.py's zip paths (e.g. "BigEarthNet-Kosovo-S2.zip")
# are relative to -- override with MODEL_DATA_ROOT if the zips live elsewhere.
DATA_ROOT = Path(os.environ.get("MODEL_DATA_ROOT", Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Preprocessing (mirrors src/data/dataset.py)
# ---------------------------------------------------------------------------
S2_BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]
S1_BANDS = ["VV", "VH"]
S2_BAND_CLIP = 4000.0
S1_DB_MIN, S1_DB_MAX = -25.0, 5.0


def _load_patch(folder: Path, patch_id: str, bands):
    arrs = []
    for b in bands:
        with rasterio.open(folder / f"{patch_id}_{b}.tif") as src:
            arrs.append(src.read(1).astype(np.float32))
    target_h = max(a.shape[0] for a in arrs)
    target_w = max(a.shape[1] for a in arrs)
    resized = []
    for a in arrs:
        if a.shape != (target_h, target_w):
            t = torch.from_numpy(a).unsqueeze(0).unsqueeze(0)
            t = torch.nn.functional.interpolate(t, size=(target_h, target_w), mode="nearest")
            a = t.squeeze(0).squeeze(0).numpy()
        resized.append(a)
    return np.stack(resized, axis=0)


def _resize(arr: np.ndarray, size: int) -> torch.Tensor:
    t = torch.from_numpy(arr).unsqueeze(0)
    t = torch.nn.functional.interpolate(t, size=(size, size), mode="bilinear", align_corners=False)
    return t.squeeze(0)


def load_s2(patch_dir: Path, patch_id: str, image_size: int) -> torch.Tensor:
    arr = _load_patch(patch_dir, patch_id, S2_BANDS)
    arr = np.clip(arr, 0, S2_BAND_CLIP) / S2_BAND_CLIP
    return _resize(arr, image_size)


def load_s1(patch_dir: Path, patch_id: str, image_size: int) -> torch.Tensor:
    arr = _load_patch(patch_dir, patch_id, S1_BANDS)
    arr = np.clip(arr, S1_DB_MIN, S1_DB_MAX)
    arr = (arr - S1_DB_MIN) / (S1_DB_MAX - S1_DB_MIN)
    return _resize(arr, image_size)


def render_s2_rgb_png(patch_dir: Path, patch_id: str) -> bytes:
    """True-color (B04/B03/B02 -> R/G/B) PNG for the tester UI's image
    component. Deliberately normalized with the exact same `S2_BAND_CLIP`
    the model itself divides by (see `load_s2` above) rather than a
    separately-tuned display stretch -- what the researcher sees in the
    browser is the same brightness/contrast the model actually receives,
    not a prettier but misleading rendering of it."""
    r, g, b = _load_patch(patch_dir, patch_id, ["B04", "B03", "B02"])
    rgb = np.stack([r, g, b], axis=-1)
    rgb = np.clip(rgb, 0, S2_BAND_CLIP) / S2_BAND_CLIP
    rgb = (rgb * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def extract_patch_bands(zip_path: Path, member_dir: str, patch_id: str, bands: list, dest_dir: Path) -> None:
    """Pulls just one patch's band tifs out of a BigEarthNet zip into
    `dest_dir`, named exactly as `_load_patch`/`render_s2_rgb_png` expect
    (`<patch_id>_<band>.tif`). Skips any file already there, so picking the
    same pair again in the UI is instant instead of re-extracting."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for band in bands:
            filename = f"{patch_id}_{band}.tif"
            dest_file = dest_dir / filename
            if dest_file.exists():
                continue
            dest_file.write_bytes(zf.read(f"{member_dir}/{filename}"))


# ---------------------------------------------------------------------------
# Q-Former projector (mirrors src/models/projector.py)
# ---------------------------------------------------------------------------
class QFormerLayer(nn.Module):
    def __init__(self, dim: int, heads: int):
        super().__init__()
        self.norm_self = nn.LayerNorm(dim)
        self.self_attn = nn.MultiheadAttention(dim, heads, batch_first=True)
        self.norm_cross = nn.LayerNorm(dim)
        self.cross_attn = nn.MultiheadAttention(dim, heads, batch_first=True)
        self.ffn = nn.Sequential(nn.LayerNorm(dim), nn.Linear(dim, dim * 4), nn.GELU(), nn.Linear(dim * 4, dim))

    def forward(self, queries, visual_kv):
        q = self.norm_self(queries)
        attn_out, _ = self.self_attn(q, q, q)
        queries = queries + attn_out
        q = self.norm_cross(queries)
        attn_out, _ = self.cross_attn(q, visual_kv, visual_kv)
        queries = queries + attn_out
        return queries + self.ffn(queries)


class QFormerProjector(nn.Module):
    def __init__(self, vis_dim, llm_dim, num_queries=32, depth=2, heads=8):
        super().__init__()
        self.in_proj = nn.Linear(vis_dim, llm_dim)
        self.queries = nn.Parameter(torch.randn(num_queries, llm_dim) * 0.02)
        self.layers = nn.ModuleList([QFormerLayer(llm_dim, heads) for _ in range(depth)])
        self.out_norm = nn.LayerNorm(llm_dim)

    def forward(self, visual_tokens):
        B = visual_tokens.shape[0]
        kv = self.in_proj(visual_tokens)
        q = self.queries.unsqueeze(0).expand(B, -1, -1)
        for layer in self.layers:
            q = layer(q, kv)
        return self.out_norm(q)


# ---------------------------------------------------------------------------
# TerraFM modality-aware token extraction (mirrors captioner.py's fix for
# L2A vs S1 routing, which TerraFM's own public API doesn't expose)
# ---------------------------------------------------------------------------
def get_intermediate_layers_modality_aware(backbone, x, is_l2a, n=1, return_class_token=True, norm=True):
    B, nc, w, h = x.shape
    tokens = backbone.patch_embed(x, is_l2a=is_l2a)
    cls_tokens = backbone.cls_token.expand(B, -1, -1)
    tokens = torch.cat((cls_tokens, tokens), dim=1)
    tokens = tokens + backbone.interpolate_pos_encoding(tokens, w, h)
    tokens = backbone.pos_drop(tokens)
    output = []
    for i, blk in enumerate(backbone.blocks):
        tokens = blk(tokens)
        if len(backbone.blocks) - i <= n:
            output.append(tokens)
    if norm:
        output = [backbone.norm(out) for out in output]
    class_tokens = [out[:, 0] for out in output]
    output = [out[:, 1:] for out in output]
    if return_class_token:
        return tuple(zip(output, class_tokens))
    return output


# ---------------------------------------------------------------------------
# Offline model wrapper
# ---------------------------------------------------------------------------
class OfflineEOCaptioner:
    def __init__(self, bundle_dir: str, device: Optional[str] = None):
        bundle = Path(bundle_dir)
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.dtype = torch.bfloat16 if self.device.type == "cuda" else torch.float32

        cfg = yaml.safe_load(open(bundle / "model_config.yaml"))
        self.image_size = cfg["image_size"]
        self.use_s1 = cfg["use_s1"]
        self.s2_is_l2a = cfg["s2_product"] == "l2a"
        self.max_answer_tokens = cfg["max_answer_tokens"]

        # TerraFM backbone: import the bundled terrafm.py directly, unmodified
        sys.path.insert(0, str(bundle.resolve()))
        from terrafm import terrafm_base, terrafm_large  # noqa: local, bundled file

        self.backbone = terrafm_base() if cfg["terrafm_variant"] == "base" else terrafm_large()
        vis_dim = 768 if cfg["terrafm_variant"] == "base" else 1024
        self.backbone.load_state_dict(torch.load(bundle / "terrafm.pth", map_location="cpu"))
        self.backbone.eval().to(self.device, dtype=self.dtype)
        for p in self.backbone.parameters():
            p.requires_grad = False

        # LLM + tokenizer: local files only, guaranteed no network calls
        self.tokenizer = AutoTokenizer.from_pretrained(bundle / "llm", local_files_only=True)
        self.llm = AutoModelForCausalLM.from_pretrained(
            bundle / "llm", local_files_only=True, torch_dtype=self.dtype
        ).to(self.device)
        self.llm.eval()

        llm_dim = self.llm.get_input_embeddings().weight.shape[-1]
        self.projector = QFormerProjector(
            vis_dim, llm_dim,
            num_queries=cfg["qformer_num_queries"], depth=cfg["qformer_depth"], heads=cfg["qformer_heads"],
        )
        self.projector.load_state_dict(torch.load(bundle / "projector.pt", map_location="cpu"))
        self.projector.eval().to(self.device, dtype=self.dtype)

        print(f"Model loaded on {self.device} ({self.dtype}).")

    @torch.no_grad()
    def encode_visual(self, s2: torch.Tensor, s1: Optional[torch.Tensor]) -> torch.Tensor:
        def run(x, is_l2a):
            (p, c) = get_intermediate_layers_modality_aware(
                self.backbone, x.to(self.dtype), is_l2a=is_l2a, n=1, return_class_token=True, norm=True
            )[0]
            return torch.cat([c.unsqueeze(1), p], dim=1)

        tokens = run(s2, is_l2a=self.s2_is_l2a)
        if s1 is not None:
            tokens = torch.cat([tokens, run(s1, is_l2a=False)], dim=1)
        return tokens

    @torch.no_grad()
    def _build_inputs_embeds(self, s2: torch.Tensor, prompt: str, s1: Optional[torch.Tensor]):
        s2 = s2.unsqueeze(0).to(self.device)
        s1 = s1.unsqueeze(0).to(self.device) if s1 is not None else None

        visual_embeds = self.projector(self.encode_visual(s2, s1)).to(self.dtype)
        instr = self.tokenizer([prompt], return_tensors="pt", padding=True).to(self.device)
        embeds = self.llm.get_input_embeddings()
        inputs_embeds = torch.cat([visual_embeds, embeds(instr["input_ids"]).to(self.dtype)], dim=1)
        mask = torch.cat(
            [
                torch.ones(visual_embeds.shape[0], visual_embeds.shape[1], device=self.device,
                           dtype=instr["attention_mask"].dtype),
                instr["attention_mask"],
            ],
            dim=1,
        )
        return inputs_embeds, mask

    def generate_stream(self, s2: torch.Tensor, prompt: str, s1: Optional[torch.Tensor] = None,
                         max_new_tokens: int = 256):
        """Same answer as a plain .generate() call would produce, but yielded
        piece by piece as the LLM produces each new token instead of blocking
        until the whole answer is ready. Runs the actual `.generate()` call on
        a background thread feeding a `TextIteratorStreamer` -- HF's supported
        pattern for getting incremental text out of `.generate()`, since
        `.generate()` itself has no callback/yield of its own."""
        inputs_embeds, mask = self._build_inputs_embeds(s2, prompt, s1)

        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        gen_kwargs = dict(
            inputs_embeds=inputs_embeds, attention_mask=mask,
            max_new_tokens=max_new_tokens, pad_token_id=self.tokenizer.pad_token_id,
            streamer=streamer,
        )

        errors = []

        def _run():
            try:
                with torch.no_grad():  # thread-local: the outer no_grad doesn't cross into this thread
                    self.llm.generate(**gen_kwargs)
            except Exception as e:
                errors.append(e)

        thread = Thread(target=_run, daemon=True)
        thread.start()
        for piece in streamer:
            yield piece
        thread.join()
        if errors:
            raise errors[0]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
BUNDLE_DIR = os.environ.get("MODEL_BUNDLE_DIR", "offline_model")

app = FastAPI(title="EOCaptioner (offline)")
model: Optional[OfflineEOCaptioner] = None


class GenerateRequest(BaseModel):
    s2_dir: str          # folder containing <patch_id>_B02.tif etc.
    patch_id: str
    prompt: str
    s1_dir: Optional[str] = None
    s1_patch_id: Optional[str] = None
    max_new_tokens: int = 256


model_load_error: Optional[str] = None


@app.on_event("startup")
def load_model():
    # Deliberately doesn't let a bad/incomplete bundle take the whole server
    # down: /preview (and the tester UI's image half) needs nothing but
    # rasterio + Pillow, so a researcher can check their S2 data renders
    # correctly before export_offline_model.py has even been run. /generate
    # is the only route that actually needs `model`, and it already reports
    # 503 "not loaded" on its own.
    global model, model_load_error
    try:
        model = OfflineEOCaptioner(bundle_dir=BUNDLE_DIR)
    except Exception as e:
        model_load_error = str(e)
        print(f"WARNING: model failed to load from '{BUNDLE_DIR}': {e}")
        print("         /preview and the UI still work; /generate will 503 until this is fixed.")


@app.get("/health")
def health():
    if model:
        return {"status": "ok", "device": str(model.device)}
    return {"status": "model_not_loaded", "error": model_load_error}


@app.get("/", response_class=HTMLResponse)
def index():
    """Serves the tester UI (static/index.html) -- a single dependency-free
    HTML file, no build step, so `python serve.py` is the entire setup."""
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/pairs")
def list_pairs():
    """The tester UI's "matching pairs" dropdown data -- see
    scripts/build_pair_index.py for how static/pairs.json is built and what
    "matching" means here. Returns [] (not an error) if it hasn't been
    built yet, so the UI can show "run the script" instead of breaking."""
    if not PAIRS_PATH.exists():
        return []
    return json.loads(PAIRS_PATH.read_text(encoding="utf-8"))


@app.get("/pairs/resolve")
def resolve_pair(id: str):
    """Lazily extracts the given pair's S1 and S2 band files (only the
    first time this id is picked -- see extract_patch_bands) and returns
    real folder paths + patch ids, in exactly the shape the image panel's
    fields and POST /generate already expect. This is what turns "pick a
    pair from a list" into "the S2/S1 fields are filled in and ready"."""
    pairs = list_pairs()
    entry = next((p for p in pairs if p["id"] == id), None)
    if not entry:
        raise HTTPException(404, f"Unknown pair id: {id}. Re-run scripts/build_pair_index.py?")

    s2_dir = CACHE_DIR / entry["id"] / "S2"
    s1_dir = CACHE_DIR / entry["id"] / "S1"
    try:
        extract_patch_bands(DATA_ROOT / entry["s2"]["zip"], entry["s2"]["member_dir"], entry["s2"]["patch_id"], S2_BANDS, s2_dir)
        extract_patch_bands(DATA_ROOT / entry["s1"]["zip"], entry["s1"]["member_dir"], entry["s1"]["patch_id"], S1_BANDS, s1_dir)
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(
            404,
            f"Couldn't find the source zip/member for this pair ({e}). "
            f"Check MODEL_DATA_ROOT (currently '{DATA_ROOT}') points at the folder holding the BigEarthNet-*.zip files.",
        )

    return {
        "s2_dir": str(s2_dir), "patch_id": entry["s2"]["patch_id"],
        "s1_dir": str(s1_dir), "s1_patch_id": entry["s1"]["patch_id"],
    }


@app.get("/preview")
def preview(s2_dir: str, patch_id: str):
    """True-color PNG for the tester UI's image component -- the same S2
    folder/patch_id a /generate call would use, so "load the image" and
    "ask about the image" always refer to the same patch. Not used by
    the model itself; purely for the researcher to see what they're
    about to ask about."""
    try:
        return Response(content=render_s2_rgb_png(Path(s2_dir), patch_id), media_type="image/png")
    except FileNotFoundError as e:
        raise HTTPException(404, f"Image file not found: {e}")
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/generate")
def generate(req: GenerateRequest):
    """Streams the answer back as plain text, flushing each token the LLM
    produces as soon as it's generated instead of waiting for the whole
    answer. Loading the input tensors happens up front, outside the stream,
    so a bad path still comes back as a normal 404/500 -- only failures
    during generation itself (after the 200 has already gone out) get
    surfaced as an inline "[error] ..." suffix in the streamed body, since
    the HTTP status can't change anymore at that point."""
    if model is None:
        raise HTTPException(503, "Model not loaded yet")
    try:
        s2 = load_s2(Path(req.s2_dir), req.patch_id, model.image_size)
        s1 = None
        if req.s1_dir and req.s1_patch_id:
            s1 = load_s1(Path(req.s1_dir), req.s1_patch_id, model.image_size)
    except FileNotFoundError as e:
        raise HTTPException(404, f"Image file not found: {e}")
    except Exception as e:
        raise HTTPException(500, str(e))

    def token_stream():
        try:
            for piece in model.generate_stream(s2, req.prompt, s1=s1, max_new_tokens=req.max_new_tokens):
                yield piece
        except Exception as e:
            yield f"\n[error] {e}"

    return StreamingResponse(token_stream(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", default="offline_model")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    BUNDLE_DIR = args.bundle
    uvicorn.run(app, host=args.host, port=args.port)
