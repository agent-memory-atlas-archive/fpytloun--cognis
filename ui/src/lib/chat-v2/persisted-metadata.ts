/**
 * Detach reactive metadata before entering IndexedDB. Preserve every field,
 * including optional metadata and admission receipts. Bytes have a separate owner.
 */
export function snapshotPersistedMetadata<T>(value: T): T {
  const seen = new Map<object, unknown>();
  function copy(item: unknown): unknown {
    if (item === null || typeof item !== 'object') return item;
    if (seen.has(item)) return seen.get(item);
    if (Array.isArray(item)) {
      const result: unknown[] = [];
      seen.set(item, result);
      for (const child of item) result.push(copy(child));
      return result;
    }
    const prototype = Object.getPrototypeOf(item);
    if (prototype !== Object.prototype && prototype !== null) return item;
    const result: Record<string, unknown> = {};
    seen.set(item, result);
    for (const key of Object.keys(item)) {
      Object.defineProperty(result, key, {
        value: copy((item as Record<string, unknown>)[key]),
        enumerable: true, writable: true, configurable: true,
      });
    }
    return result;
  }
  // Unsupported values fail here, not inside a request event callback.
  return structuredClone(copy(value)) as T;
}
