/**
 * state/useToastStore.ts
 * =======================
 * The one transient confirmation channel in the app: a single centred
 * toast, auto-dismissed, used for actions that succeeded and need
 * acknowledging but not explaining — an item added to context, a report
 * requested, a session loaded.
 *
 * Deliberately NOT used for errors. Server errors come back with a
 * user-safe `message` (api/types.ts ApiErrorBody) and are shown next to
 * the thing that caused them — the prompt input, the offending chip — so
 * the researcher can act on them. A toast that disappears is the wrong
 * place for anything the user has to fix.
 *
 * One toast at a time by design: a queue would let a burst of adds stack
 * up and outlive the interaction that caused them.
 */
import { create } from "zustand";

const TOAST_DURATION_MS = 2600;

interface ToastState {
  message: string | null;
  show: (message: string) => void;
  dismiss: () => void;
}

let timer: ReturnType<typeof setTimeout> | null = null;

export const useToastStore = create<ToastState>((set) => ({
  message: null,
  show: (message) => {
    if (timer) clearTimeout(timer);
    set({ message });
    timer = setTimeout(() => set({ message: null }), TOAST_DURATION_MS);
  },
  dismiss: () => {
    if (timer) clearTimeout(timer);
    set({ message: null });
  },
}));
