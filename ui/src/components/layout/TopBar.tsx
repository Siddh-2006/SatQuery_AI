/**
 * components/layout/TopBar.tsx
 * ==============================
 * The slim top bar (DESIGN.md §1): brand, the session switcher (§8), and
 * the three view controls — basemap, region, resolution (§2.7).
 *
 * All three controls on the right are VIEW settings: they change how the
 * map is drawn and where it looks, never which patch data is selectable.
 * They are grouped together, away from the session controls on the left,
 * for exactly that reason — nothing on the right of this bar can alter the
 * researcher's context or their answers.
 */
import { SessionSwitcher } from "./SessionSwitcher";
import { useMapStore, REGIONS, type RegionKey } from "../../state/useMapStore";

interface LabelledSelectProps {
  id: string;
  label: string;
  width: number;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}

function LabelledSelect({ id, label, width, value, onChange, children }: LabelledSelectProps) {
  return (
    <div className="flex items-center gap-[5.6px]">
      <label htmlFor={id} className="text-[11px] text-neutral-500">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="input min-h-[32px] text-[13px]"
        style={{ width }}
      >
        {children}
      </select>
    </div>
  );
}

export function TopBar() {
  const basemapStyle = useMapStore((s) => s.basemapStyle);
  const setBasemapStyle = useMapStore((s) => s.setBasemapStyle);
  const region = useMapStore((s) => s.region);
  const setRegion = useMapStore((s) => s.setRegion);
  const resolution = useMapStore((s) => s.resolution);
  const setResolution = useMapStore((s) => s.setResolution);

  return (
    <header
      className="relative z-40 flex flex-none items-center gap-[16.8px] px-[11.2px] py-[8.4px]"
      style={{
        background: "linear-gradient(180deg,#1b1d2d,var(--color-bg))",
        boxShadow: "0 1px 0 var(--color-divider)",
      }}
    >
      <div className="flex items-center gap-[8.4px]">
        <i className="ph ph-globe-hemisphere-east text-[19px] text-accent" aria-hidden="true" />
        <span className="font-heading text-[17px] font-medium tracking-[-0.01em]">SatQuery AI</span>
      </div>

      <SessionSwitcher />

      <div className="ml-auto flex items-center gap-[11.2px]">
        <LabelledSelect
          id="basemap-select"
          label="Basemap"
          width={150}
          value={basemapStyle}
          onChange={(value) => setBasemapStyle(value as "satellite" | "streets")}
        >
          <option value="satellite">Satellite imagery</option>
          <option value="streets">Streets</option>
        </LabelledSelect>

        <LabelledSelect
          id="region-select"
          label="Region"
          width={130}
          value={region}
          onChange={(value) => setRegion(value as RegionKey)}
        >
          {Object.entries(REGIONS).map(([key, meta]) => (
            <option key={key} value={key}>
              {meta.label}
            </option>
          ))}
        </LabelledSelect>

        <LabelledSelect
          id="resolution-select"
          label="Res"
          width={96}
          value={resolution}
          onChange={(value) => setResolution(value as "10m" | "20m" | "60m")}
        >
          <option value="10m">10 m</option>
          <option value="20m">20 m</option>
          <option value="60m">60 m</option>
        </LabelledSelect>
      </div>
    </header>
  );
}
