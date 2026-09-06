/**
 * mocks/placeholderImage.ts
 * ==========================
 * We have the real Luxembourg/Kosovo patch footprints and capture dates
 * now (see mocks/fixtures/patches.ts), but not rendered band-composite
 * imagery — that's produced server-side (DESIGN.md §2.6), never decoded
 * client-side. Until a real backend is serving it, every "preview" URL in
 * the mock API returns a small inline
 * SVG data-URI instead of a real image, so every viewer component
 * (PatchViewerDrawer, context chip thumbnails, temporal browser rows) has
 * something to render and can be visually verified end-to-end right now.
 *
 * Swapping these for real imagery later is purely a mocks/ concern — no
 * component that displays a `previewUrl`/`thumbnailUrl` needs to change,
 * since they only ever treat it as an opaque <img src>.
 */

/** Deterministic pastel background per label, so the same patch/composite
 *  always renders the same placeholder color across reloads. */
function colorFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  const hue = hash % 360;
  return `hsl(${hue}, 55%, 55%)`;
}

/**
 * Builds the raw SVG markup for a small labeled placeholder tile. Used
 * directly (with an `image/svg+xml` content type) by the mock
 * `GET /api/patches/:id/preview` handler, so that endpoint behaves like a
 * real image-serving endpoint rather than a data URI baked into JSON.
 */
export function placeholderSvgString(label: string, width = 256, height = 256): string {
  const bg = colorFor(label);
  return `
    <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
      <rect width="100%" height="100%" fill="${bg}" />
      <rect width="100%" height="100%" fill="black" opacity="0.15" />
      <text x="50%" y="50%" font-family="monospace" font-size="13"
            fill="white" text-anchor="middle" dominant-baseline="middle">
        ${escapeXml(label)}
      </text>
      <text x="50%" y="62%" font-family="monospace" font-size="10"
            fill="white" opacity="0.8" text-anchor="middle">
        (placeholder — real imagery pending)
      </text>
    </svg>`.trim();
}

/**
 * Same tile as `placeholderSvgString`, but as a data: URI — for fixture
 * fields that are plain JSON string URLs (timeseries thumbnails, upload
 * previews, mock evidence overlays) rather than their own HTTP route.
 *
 * Percent-encoded (not base64) deliberately: `btoa` only handles Latin-1
 * (code points 0–255) and throws on anything past it, which this tile's
 * text easily contains (an em dash, or a patch label with non-ASCII
 * characters) — `encodeURIComponent` handles the full Unicode string
 * without that trap, and browsers render percent-encoded SVG data URIs
 * exactly the same as base64 ones.
 * @param label short text drawn on the tile, e.g. "LUX-0417 · true_color"
 */
export function placeholderPreview(label: string, width = 256, height = 256): string {
  return `data:image/svg+xml,${encodeURIComponent(placeholderSvgString(label, width, height))}`;
}

function escapeXml(s: string): string {
  return s.replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c]!));
}
