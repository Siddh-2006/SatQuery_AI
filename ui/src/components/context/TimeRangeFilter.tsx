/**
 * components/context/TimeRangeFilter.tsx
 * ========================================
 * The date-range inputs for the temporal browser (DESIGN.md §4.4).
 *
 * Native date inputs on purpose: they get the platform's own calendar,
 * keyboard entry and locale handling for free, and the app's fixed
 * `color-scheme: dark` (styles/index.css) is what makes their
 * browser-drawn chrome legible on this ground.
 *
 * Uncontrolled range semantics are deliberately loose — an empty end date
 * means "no upper bound", not "invalid" — because a researcher narrowing
 * from one end shouldn't have to fill in a bound they don't care about.
 */
interface TimeRangeFilterProps {
  from: string;
  to: string;
  onChange: (range: { from: string; to: string }) => void;
}

export function TimeRangeFilter({ from, to, onChange }: TimeRangeFilterProps) {
  return (
    <div className="flex items-center gap-[5.6px]">
      <input
        type="date"
        value={from}
        max={to || undefined}
        onChange={(event) => onChange({ from: event.target.value, to })}
        aria-label="From date"
        className="input min-h-[28px] text-[11.5px]"
      />
      <span className="flex-none text-[11px] text-neutral-500">to</span>
      <input
        type="date"
        value={to}
        min={from || undefined}
        onChange={(event) => onChange({ from, to: event.target.value })}
        aria-label="To date"
        className="input min-h-[28px] text-[11.5px]"
      />
    </div>
  );
}
