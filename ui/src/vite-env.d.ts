/// <reference types="vite/client" />

// Extends Vite's built-in ImportMetaEnv with the one custom env var this
// app reads (see api/client.ts) — optional, so existing same-origin/MSW
// setups that never set it keep working unchanged.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}
