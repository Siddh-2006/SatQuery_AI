"""
app/api/uploads.py
=====================
`POST /api/uploads` -- ui/DESIGN.md §4.2/§6.4. Real implementation: saves
the file, detects what metadata it can (`data/upload_store.py`), and
serves a real preview PNG. See `orchestrator/DESIGN.md` §13 for the one
honest limitation: the upload is fully storable/previewable, but querying
it with EOCaptioner isn't wired up yet (rejected by `app/compatibility.py`
at query time, not here).
"""
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from data.upload_store import extension_of, preview_path_for, save_upload

router = APIRouter()


@router.post("/api/uploads")
async def post_upload(file: UploadFile = File(...)):
    content = await file.read()
    try:
        result = save_upload(file.filename, content)
    except ValueError as e:
        code, _, message = str(e).partition(":")
        status = 415 if code == "unsupported_format" else 400
        return JSONResponse({"error": {"code": code, "message": message, "details": {"filename": file.filename}}}, status_code=status)

    return JSONResponse(
        {
            "fileId": result.file_id,
            "originalFilename": result.original_filename,
            "format": result.format,
            "detectedModality": result.detected_modality,
            "detectedLocation": result.detected_location,
            "detectedTimestamp": result.detected_timestamp,
            "previewUrl": f"/api/uploads/{result.file_id}/preview",
        }
    )


@router.get("/api/uploads/{file_id}/preview")
async def get_upload_preview(file_id: str):
    """Not one of ui/DESIGN.md's documented endpoints by name, but exactly
    what `previewUrl` above needs to point at -- the upload response's
    `previewUrl` is just a URL string the `<img>` tag uses directly, same
    pattern as `patchPreviewUrl` in `ui/src/api/client.ts`."""
    path = preview_path_for(file_id)
    if path is None:
        return JSONResponse({"error": {"code": "corrupt_file", "message": "Unknown upload id.", "details": {}}}, status_code=404)
    return FileResponse(path, media_type="image/png")
