/**
 * components/context/UploadDialog.tsx
 * =====================================
 * Bringing a researcher's own image into context (DESIGN.md §4.2).
 *
 * Three states, one dialog: pick a file, watch it upload, then confirm what
 * the server made of it. The third state is the reason this is a dialog and
 * not a file button — an upload arrives with metadata DETECTED, not given,
 * and a file with no modality can't be paired or reasoned about until
 * someone says which sensor it came from. So the result is shown as a
 * PENDING card (dashed, same signal as an unconfirmed map selection) with
 * the gaps exposed, and "Add to context" stays disabled until they're
 * filled.
 *
 * Format policy is stated but not enforced here: the fine print says what
 * is accepted, and the note says the authoritative check is server-side.
 * Client-side validation of a GeoTIFF's contents would be a lie — we never
 * decode raster data in the browser.
 *
 * The progress bar reflects request state, not bytes: fetch() gives no
 * upload progress. Swapping in XMLHttpRequest would give real percentages
 * if that ever matters more than keeping one fetch-based api/client.
 */
import { useRef, useState } from "react";
import { useContextStore } from "../../state/useContextStore";
import { useToastStore } from "../../state/useToastStore";
import { postUpload } from "../../api/client";
import { ApiError, type Modality, type UploadedImageRef } from "../../api/types";

/** Files the mock backend recognises — one with full metadata, one with
 *  none, so both paths through this dialog are reachable without the
 *  researcher having to find a GeoTIFF. */
const SAMPLE_FILES = ["cartosat_scene_014.tif", "benchmark_rs_0042.png"];

export function UploadDialog() {
  const uploadDialogOpen = useContextStore((s) => s.uploadDialogOpen);
  const closeUploadDialog = useContextStore((s) => s.closeUploadDialog);
  const pendingUpload = useContextStore((s) => s.pendingUpload);
  const setPendingUpload = useContextStore((s) => s.setPendingUpload);
  const patchPendingUpload = useContextStore((s) => s.patchPendingUpload);
  const clearPendingUpload = useContextStore((s) => s.clearPendingUpload);
  const addItemToActiveSet = useContextStore((s) => s.addItemToActiveSet);
  const showToast = useToastStore((s) => s.show);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  if (!uploadDialogOpen) return null;

  async function upload(file: File) {
    setAddError(null);
    setPendingUpload({ status: "uploading", file, progress: 8 });
    // Held at 92% until the response lands: fetch() reports no upload
    // progress, and a bar that sits at 100% while nothing has come back is
    // worse than one that visibly waits.
    const tick = setInterval(() => {
      const current = useContextStore.getState().pendingUpload;
      if (current?.status === "uploading") patchPendingUpload({ progress: Math.min(current.progress + 9, 92) });
    }, 150);

    try {
      const result = await postUpload(file);
      patchPendingUpload({ status: "ready", progress: 100, result });
    } catch (caught) {
      patchPendingUpload({
        status: "error",
        error: caught instanceof ApiError ? caught.message : "That file couldn't be uploaded.",
      });
    } finally {
      clearInterval(tick);
    }
  }

  function handleSample(name: string) {
    // The mock backend keys its detected metadata off the filename, so an
    // empty blob with the right name exercises the real code path.
    void upload(new File([new Blob([])], name));
  }

  const result = pendingUpload?.result;
  const modality: Modality | undefined = result?.detectedModality ?? pendingUpload?.manualModality;
  const needsModality = Boolean(result) && !result?.detectedModality;
  const canAdd = Boolean(result) && Boolean(modality);

  function handleAdd() {
    if (!result || !modality) return;
    const item: UploadedImageRef = {
      kind: "uploaded_image",
      fileId: result.fileId,
      originalFilename: result.originalFilename,
      format: result.format,
      detectedModality: modality,
      detectedLocation: result.detectedLocation,
      detectedTimestamp: result.detectedTimestamp ?? pendingUpload?.manualTimestamp ?? null,
      previewUrl: result.previewUrl,
    };
    const outcome = addItemToActiveSet(item);
    if (outcome.ok) {
      showToast(`${result.originalFilename} added to context`);
      closeUploadDialog();
    } else if (outcome.needsPairChoice) {
      closeUploadDialog();
    } else {
      setAddError(outcome.reason ?? null);
    }
  }

  return (
    <div className="dialog-backdrop z-[80]" role="dialog" aria-modal="true" aria-label="Upload image">
      <div className="dialog elev-lg">
        <div className="flex items-start gap-[8.4px]">
          <h4 className="dialog-title flex-1">Upload image</h4>
          <button type="button" onClick={closeUploadDialog} aria-label="Close" className="btn-bare h-[24px] w-[24px] text-[14px]">
            <i className="ph ph-x" />
          </button>
        </div>

        {/* --- Idle: pick a file ------------------------------------- */}
        {!pendingUpload && (
          <>
            <div
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragging(false);
                const file = event.dataTransfer.files[0];
                if (file) void upload(file);
              }}
              onClick={() => inputRef.current?.click()}
              className="flex cursor-pointer flex-col items-center gap-[5.6px] rounded-md p-[22.4px] text-center"
              style={{
                border: `1px dashed ${isDragging ? "var(--color-accent)" : "var(--color-neutral-700)"}`,
                background: isDragging ? "var(--color-accent-900)" : "transparent",
              }}
            >
              <i className="ph ph-upload-simple text-[24px] text-accent" aria-hidden="true" />
              <span className="text-[13px]">Drag a file here, or pick one of the samples</span>
              <span className="text-[11.5px] leading-[1.5] text-neutral-500">
                .tif / .tiff, plus .png / .jpg restricted to the prescribed public benchmark datasets. The
                authoritative check is server-side.
              </span>
              <input
                ref={inputRef}
                type="file"
                accept=".tif,.tiff,.png,.jpg,.jpeg"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void upload(file);
                }}
              />
            </div>

            <div className="flex flex-col items-start gap-[5.6px]">
              {SAMPLE_FILES.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => handleSample(name)}
                  className="btn btn-secondary font-mono text-[12px]"
                >
                  {name}
                </button>
              ))}
            </div>
          </>
        )}

        {/* --- Uploading --------------------------------------------- */}
        {pendingUpload?.status === "uploading" && (
          <div className="flex flex-col gap-[5.6px]">
            <span className="text-[12.5px] text-neutral-300">
              POST /api/uploads — {pendingUpload.file.name}
            </span>
            <div className="h-[5px] overflow-hidden rounded-[3px] bg-neutral-900">
              <div
                className="h-full rounded-[3px] bg-accent transition-[width] duration-[180ms] ease-linear"
                style={{ width: `${pendingUpload.progress}%` }}
              />
            </div>
          </div>
        )}

        {/* --- Failed ------------------------------------------------- */}
        {pendingUpload?.status === "error" && (
          <p className="m-0 flex items-start gap-[6px] rounded-sm bg-accent-900 px-[8px] py-[6px] text-[11.5px] leading-[1.45] text-accent-200">
            <i className="ph ph-warning-circle mt-[2px] text-[12px]" aria-hidden="true" />
            {pendingUpload.error}
          </p>
        )}

        {/* --- Ready: confirm what the server detected ---------------- */}
        {result && (
          <>
            <div
              className="flex items-start gap-[11.2px] rounded-md p-[8.4px]"
              style={{ border: "1px dashed var(--color-accent-300)" }}
            >
              <div
                className="flex h-[64px] w-[64px] flex-none items-center justify-center rounded-sm text-[20px] text-accent-300"
                style={{ background: "linear-gradient(135deg,#292b31,#3f424d)" }}
                aria-hidden="true"
              >
                <i className="ph ph-file-image" />
              </div>
              <div className="flex min-w-0 flex-1 flex-col gap-[2.8px]">
                <span className="truncate font-mono text-[12.5px]">{result.originalFilename}</span>
                <span className="text-[11.5px] leading-[1.45] text-neutral-500">
                  {[
                    result.format,
                    result.detectedModality ?? "no modality detected",
                    result.detectedLocation
                      ? `${result.detectedLocation.lat.toFixed(2)} / ${result.detectedLocation.lon.toFixed(2)}`
                      : "no geodata",
                    result.detectedTimestamp ?? "no date",
                  ].join(" · ")}
                </span>
                <span className="tag tag-neutral self-start">pending — not in context yet</span>
              </div>
            </div>

            {needsModality && (
              <>
                <p className="m-0 text-[11.5px] leading-[1.5] text-accent-200">
                  No modality or geodata in this file. Fill in modality before it can be added.
                </p>
                <div className="seg self-start">
                  {(["optical", "sar"] as Modality[]).map((option) => (
                    <label key={option} className="seg-opt text-[12px]">
                      <input
                        type="radio"
                        name="manual-modality"
                        value={option}
                        checked={pendingUpload?.manualModality === option}
                        onChange={() => patchPendingUpload({ manualModality: option })}
                      />
                      {option === "optical" ? "Optical" : "SAR"}
                    </label>
                  ))}
                </div>
                <div className="flex items-center gap-[8.4px]">
                  <label htmlFor="manual-date" className="flex-none text-[11px] text-neutral-500">
                    Capture date (optional)
                  </label>
                  <input
                    id="manual-date"
                    type="date"
                    value={pendingUpload?.manualTimestamp ?? ""}
                    onChange={(event) => patchPendingUpload({ manualTimestamp: event.target.value })}
                    className="input min-h-[28px] text-[11.5px]"
                  />
                </div>
              </>
            )}

            {addError && (
              <p className="m-0 flex items-start gap-[6px] rounded-sm bg-accent-900 px-[8px] py-[6px] text-[11.5px] leading-[1.45] text-accent-200">
                <i className="ph ph-warning-circle mt-[2px] text-[12px]" aria-hidden="true" />
                {addError}
              </p>
            )}

            <div className="dialog-actions">
              <button
                type="button"
                onClick={() => {
                  clearPendingUpload();
                  setAddError(null);
                }}
                className="btn btn-secondary text-[13px]"
              >
                Discard
              </button>
              <button type="button" onClick={handleAdd} disabled={!canAdd} className="btn btn-primary text-[13px]">
                Add to context
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
