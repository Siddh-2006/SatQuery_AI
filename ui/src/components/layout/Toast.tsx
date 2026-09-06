/**
 * components/layout/Toast.tsx
 * =============================
 * The single centred confirmation toast, driven by useToastStore. Mounted
 * once in App.tsx, never per-feature.
 *
 * Success only — errors are shown next to whatever caused them, because a
 * message that vanishes is no use for something the researcher has to act
 * on (see useToastStore's header for the full reasoning).
 */
import { useToastStore } from "../../state/useToastStore";

export function Toast() {
  const message = useToastStore((s) => s.message);
  if (!message) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="elev-md fixed bottom-[22.4px] left-1/2 z-[90] flex -translate-x-1/2 items-center gap-[8.4px] rounded-md bg-surface px-[11.2px] py-[8.4px] text-[12.5px]"
    >
      <i className="ph ph-check-circle text-[15px] text-accent" aria-hidden="true" />
      {message}
    </div>
  );
}
