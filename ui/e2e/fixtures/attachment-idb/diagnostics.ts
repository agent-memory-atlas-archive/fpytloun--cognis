/** Fixture-only, content-free observations. Never changes owner state/results. */
export function phase(name: string): void {
  window.dispatchEvent(new CustomEvent('attachment-diagnostic-phase', { detail: name }));
}
export function errorName(error: unknown): string {
  const name = error instanceof Error || error instanceof DOMException ? error.name : '';
  return ['Error', 'TypeError', 'ReferenceError', 'SyntaxError', 'DataCloneError',
    'AbortError', 'InvalidStateError', 'TransactionInactiveError', 'QuotaExceededError',
    'SecurityError', 'NotFoundError'].includes(name) ? name : 'UnknownError';
}
export async function observed<T>(name: string, operation: () => Promise<T>): Promise<T> {
  phase(`${name}:start`);
  try {
    const result = await operation();
    phase(`${name}:settled`);
    return result;
  } catch (error) {
    phase(`${name}:rejected:${errorName(error)}`);
    throw error;
  }
}
