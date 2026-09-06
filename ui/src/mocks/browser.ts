/**
 * mocks/browser.ts
 * =================
 * Sets up the Mock Service Worker instance for the browser (as opposed to
 * MSW's Node setup, which we don't use here). Started conditionally from
 * main.tsx — see that file for how/when mocking turns on.
 */
import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);
