/**
 * components/context/TemporalBrowser.tsx
 * ========================================
 * Browses every capture at one location (DESIGN.md §4.4) — the only place
 * in the app where a patch's OTHER dates are reachable.
 *
 * This is how a bitemporal pair gets built. The map shows one footprint per
 * location, not one per capture, so picking "the same place in 2019" is not
 * something a map click can express; it needs a list of that location's
 * timeseries. Hence "Add" here rather than anywhere else, and hence the
 * footnote naming the endpoint — the timeseries is a different query from
 * the footprint layer, and that's worth knowing when the two disagree.
 *
 * The location is set from the MAP, not picked from a list here: a
 * footprint popover's "Add to temporal explorer" button sets
 * `useMapStore.temporalPatchId` (see PatchPopover). With thousands of real
 * patches now indexed, a `<select>` of every location would be an
 * unusably long, unsearchable list — clicking the place you mean on the
 * map is both faster and how a researcher already thinks about "this
 * location", so that's the only way in.
 *
 * "View" opens the patch viewer without touching context, the same
 * inspect-before-committing pattern as the popover's Inspect.
 */
import { useEffect, useState } from "react";
import { TimeRangeFilter } from "./TimeRangeFilter";
import { useMapStore } from "../../state/useMapStore";
import { useContextStore } from "../../state/useContextStore";
import { useToastStore } from "../../state/useToastStore";
import { getPatchTimeseries } from "../../api/client";
import type { PatchRef, TimeseriesEntry } from "../../api/types";

export function TemporalBrowser() {
  const footprints = useMapStore((s) => s.footprints);
  const patchId = useMapStore((s) => s.temporalPatchId);
  const setTemporalPatchId = useMapStore((s) => s.setTemporalPatchId);
  const openDrawerFor = useMapStore((s) => s.openDrawerFor);
  const addItemToActiveSet = useContextStore((s) => s.addItemToActiveSet);
  const activeSet = useContextStore((s) => s.contextSets.find((c) => c.id === s.activeContextSetId) ?? null);
  const showToast = useToastStore((s) => s.show);

  const [entries, setEntries] = useState<TimeseriesEntry[]>([]);
  const [range, setRange] = useState({ from: "", to: "" });

  useEffect(() => {
    if (!patchId) {
      setEntries([]);
      return;
    }
    let cancelled = false;
    getPatchTimeseries(patchId)
      .then((result) => {
        if (!cancelled) setEntries(result);
      })
      .catch(() => {
        if (!cancelled) setEntries([]);
      });
    return () => {
      cancelled = true;
    };
  }, [patchId]);

  // ISO dates compare correctly as strings, so no Date parsing is needed —
  // and an empty bound simply doesn't constrain.
  const visible = entries.filter(
    (entry) => (!range.from || entry.timestamp >= range.from) && (!range.to || entry.timestamp <= range.to),
  );

  const feature = footprints?.features.find((f) => f.properties.patchId === patchId);
  const isSetFull = (activeSet?.items.length ?? 0) >= 2;

  function handleAdd(entry: TimeseriesEntry) {
    if (!feature) return;
    const item: PatchRef = {
      kind: "patch",
      patchId: entry.patchId,
      lat: feature.properties.lat,
      lon: feature.properties.lon,
      timestamp: entry.timestamp,
      availableModalities: feature.properties.availableModalities,
      bandSelection: "default_rgb",
    };
    const result = addItemToActiveSet(item);
    if (result.ok) showToast(`${entry.patchId} · ${entry.timestamp} added to context`);
  }

  return (
    <section className="flex flex-col gap-[8.4px]">
      <h5 className="text-[14px]">Temporal browser</h5>

      {!patchId || !feature ? (
        <p className="m-0 text-[12.5px] leading-[1.5] text-neutral-500">
          Click a footprint on the map, then choose <strong>“Add to temporal explorer”</strong> in its
          popover to browse every other capture at that location here.
        </p>
      ) : (
        <>
          <div className="flex items-center gap-[5.6px]">
            <span className="min-w-0 flex-1 truncate text-[12.5px]">
              {feature.properties.patchId} — {feature.properties.label}
            </span>
            <button
              type="button"
              onClick={() => setTemporalPatchId(null)}
              title="Clear — pick a different location on the map"
              className="btn-bare h-[22px] w-[22px] flex-none text-[13px]"
              aria-label="Clear location"
            >
              <i className="ph ph-x" />
            </button>
          </div>

          <TimeRangeFilter from={range.from} to={range.to} onChange={setRange} />

          <div className="flex flex-col gap-[5.6px]">
            {visible.length === 0 && (
              <p className="m-0 text-[11.5px] text-neutral-600">No captures in this date range.</p>
            )}

            {visible.map((entry) => (
              <div
                key={entry.timestamp}
                className="flex items-center gap-[8.4px] rounded-sm bg-neutral-900 p-[5.6px]"
              >
                <div
                  className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-sm text-[13px] text-accent-300"
                  style={{ background: "linear-gradient(135deg,#292b31,#3f424d)" }}
                  aria-hidden="true"
                >
                  <i className="ph ph-image" />
                </div>
                <span className="min-w-0 flex-1 text-[12.5px] tabular-nums">{entry.timestamp}</span>
                <button
                  type="button"
                  onClick={() => openDrawerFor(entry.patchId)}
                  className="btn btn-secondary px-[8px] py-[3px] text-[12px]"
                >
                  View
                </button>
                <button
                  type="button"
                  onClick={() => handleAdd(entry)}
                  disabled={isSetFull}
                  title={isSetFull ? "This context set already holds two items" : undefined}
                  className="btn btn-primary px-[8px] py-[3px] text-[12px]"
                >
                  Add
                </button>
              </div>
            ))}
          </div>

          <p className="m-0 text-[11px] leading-[1.45] text-neutral-600">
            GET /api/patches/{patchId}/timeseries · “Add” builds a bitemporal pair
          </p>
        </>
      )}
    </section>
  );
}
