/**
 * components/layout/CollapsiblePanel.tsx
 * ========================================
 * The left/right side-panel shell (DESIGN.md §1): a fixed-width panel that
 * collapses to a 44px icon rail, remembering its collapsed state per
 * browser (localStorage) so reloading doesn't reopen a panel the
 * researcher deliberately tucked away.
 *
 * Collapsing never unmounts `children` — it hides them — so whatever state
 * lives inside (the chat thread, a half-filled date range) survives the
 * panel being closed and reopened.
 *
 * The rail is not decoration: it carries the same icons as the sections
 * inside, so a collapsed panel still says what it holds. `railBadge` lets
 * the chat panel show its message count while closed, which is the one
 * piece of panel content that matters when you can't see the panel.
 *
 * This component knows nothing about what's inside it — that's what lets
 * one shell serve two panels with completely different contents.
 */
import { useEffect, useState, type ReactNode } from "react";

interface CollapsiblePanelProps {
  side: "left" | "right";
  /** Expanded width in px. */
  width: number;
  /** localStorage key this panel's collapsed state is persisted under.
   *  Must be unique per panel instance. */
  storageKey: string;
  title: string;
  /** Phosphor class names (e.g. "ph-stack"); the first renders in accent as
   *  the rail's primary marker. */
  railIcons: string[];
  railLabel: string;
  railBadge?: string;
  /** True (default) wraps children in an internal scroller. Pass false when
   *  the child manages its own scrolling regions, as ChatPanel does. */
  scroll?: boolean;
  children: ReactNode;
}

function readPersistedCollapsed(storageKey: string): boolean {
  try {
    return localStorage.getItem(storageKey) === "true";
  } catch {
    // Privacy mode / disabled storage throws on access — default to
    // "expanded" rather than taking the layout down with it.
    return false;
  }
}

export function CollapsiblePanel({
  side,
  width,
  storageKey,
  title,
  railIcons,
  railLabel,
  railBadge,
  scroll = true,
  children,
}: CollapsiblePanelProps) {
  const [collapsed, setCollapsed] = useState(() => readPersistedCollapsed(storageKey));

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, String(collapsed));
    } catch {
      // Losing the persisted preference is harmless — it just won't
      // survive a reload. See readPersistedCollapsed.
    }
  }, [collapsed, storageKey]);

  // Panels are separated by a hairline drawn as a box-shadow rather than a
  // border, so the divider doesn't participate in the flex width and the
  // panel's stated width is its real width.
  const edge = side === "left" ? "1px 0 0 var(--color-divider)" : "-1px 0 0 var(--color-divider)";

  const collapseIcon = side === "left" ? "ph-caret-left" : "ph-caret-right";
  const expandIcon = side === "left" ? "ph-caret-right" : "ph-caret-left";

  if (collapsed) {
    return (
      <div
        className="flex w-[44px] flex-none flex-col items-center gap-[11.2px] py-[8.4px]"
        style={{ boxShadow: edge }}
      >
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          aria-label={`Expand ${title}`}
          title={`Expand ${title}`}
          className="btn-bare h-[26px] w-[26px] text-[14px]"
        >
          <i className={`ph ${expandIcon}`} />
        </button>
        {railIcons.map((icon, index) => (
          <i
            key={icon}
            className={`ph ${icon} text-[15px] ${index === 0 ? "text-accent" : "text-neutral-500"}`}
            aria-hidden="true"
          />
        ))}
        {railBadge && <span className="tag tag-accent px-[6px] py-0 text-[10px]">{railBadge}</span>}
        <span
          className="mt-[2.8px] text-[10px] uppercase tracking-[0.1em] text-neutral-600"
          style={{ writingMode: "vertical-rl" }}
        >
          {railLabel}
        </span>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-none flex-col" style={{ width, boxShadow: edge }}>
      <div className="flex flex-none items-center justify-between px-[11.2px] py-[8.4px]">
        <span className="text-[10px] uppercase tracking-[0.1em] text-neutral-500">{title}</span>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          aria-label={`Collapse ${title}`}
          title={`Collapse ${title}`}
          className="btn-bare h-[26px] w-[26px] text-[14px]"
        >
          <i className={`ph ${collapseIcon}`} />
        </button>
      </div>
      <div className={`min-h-0 flex-1 ${scroll ? "overflow-y-auto" : "flex flex-col"}`}>{children}</div>
    </div>
  );
}
