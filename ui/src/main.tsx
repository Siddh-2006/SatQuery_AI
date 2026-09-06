/**
 * main.tsx
 * =========
 * App entry point. The only thing worth noting here is how mocking turns
 * on: in development we start the Mock Service Worker (mocks/browser.ts)
 * BEFORE rendering anything, so no component ever races a real fetch
 * against an unstarted worker. To point this build at a real orchestrator
 * instead, either build for production (`import.meta.env.DEV` is false) or
 * delete the `enableMocking()` call below — nothing else in the app needs
 * to change, since api/client.ts always calls the same relative /api/...
 * paths regardless of who's answering them.
 *
 * Phosphor's icon font is imported here (once, globally) rather than per
 * component: the icons are used as <i className="ph ph-…" /> glyphs
 * throughout, which needs the stylesheet present before first paint.
 */
import React from "react";
import ReactDOM from "react-dom/client";
import "@phosphor-icons/web/regular";
import App from "./App";
import "./styles/index.css";

async function enableMocking() {
  if (!import.meta.env.DEV) return;
  const { worker } = await import("./mocks/browser");
  // "bypass" (rather than "warn") for unhandled requests: this app is
  // expected to only ever call the /api/... endpoints mocks/handlers.ts
  // implements, so anything else (e.g. MapLibre's own tile requests) should
  // pass through untouched rather than logging noise.
  await worker.start({ onUnhandledRequest: "bypass" });
}

enableMocking().then(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
