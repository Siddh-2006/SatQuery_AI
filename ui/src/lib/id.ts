/**
 * lib/id.ts
 * =========
 * One tiny helper so we don't pull in a whole dependency (uuid/nanoid) just
 * to generate client-side ids for things like a new ContextSet or a pending
 * selection before the backend has assigned anything. `crypto.randomUUID`
 * is available in every browser we target (and in Node 19+, for tests).
 *
 * Never use this for ids that must match something the backend generates
 * (e.g. a real patchId, sessionId, fileId) — those always come from a
 * response, not from here.
 */
export function newLocalId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().slice(0, 8)}`;
}
