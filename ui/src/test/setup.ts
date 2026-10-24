import '@testing-library/jest-dom/vitest';
import { TestWebLocks } from './web-locks';

Object.defineProperty(navigator, 'locks', { configurable: true, value: new TestWebLocks() });

declare global {
  var __sveltekit_dev: { env?: Record<string, string | undefined> } | undefined;
}

globalThis.__sveltekit_dev = {
  ...(globalThis.__sveltekit_dev ?? {}),
  env: globalThis.__sveltekit_dev?.env ?? {}
};
