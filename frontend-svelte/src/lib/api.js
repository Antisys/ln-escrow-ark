/**
 * Backward-compatible shim.
 * All API functions now live in lib/api/ subdirectory.
 * This re-exports everything so existing `import { ... } from '$lib/api.js'` keeps working.
 */
export * from './api/index.js';
