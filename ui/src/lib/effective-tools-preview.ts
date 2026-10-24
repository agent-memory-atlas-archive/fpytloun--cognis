/**
 * Debounced, deduplicated effective-tools preview requests for agent editors.
 *
 * The editor recomputes the preview payload whenever any reactive form field
 * changes, including writes made by rendered controls after a preview result
 * replaces the tool list. Only payloads that differ from the last requested one
 * are sent, and a newer request aborts the in-flight one, so re-renders cannot
 * turn into an unbounded request loop.
 */
export interface EffectiveToolsPreviewScheduler<TPayload, TResult> {
  /** Record a payload whose result is already applied (e.g. initial load). */
  prime(payload: TPayload): void;
  /** Request a preview for the payload unless it matches the last request. */
  schedule(payload: TPayload): void;
  /** Cancel pending and in-flight work. */
  dispose(): void;
}

export function createEffectiveToolsPreviewScheduler<TPayload, TResult>(options: {
  fetch: (payload: TPayload, signal: AbortSignal) => Promise<TResult>;
  onResult: (result: TResult) => void;
  debounceMs?: number;
}): EffectiveToolsPreviewScheduler<TPayload, TResult> {
  const debounceMs = options.debounceMs ?? 200;
  let lastKey: string | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;

  function cancelPending(): void {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function abortInFlight(): void {
    controller?.abort();
    controller = null;
  }

  return {
    prime(payload) {
      cancelPending();
      abortInFlight();
      lastKey = JSON.stringify(payload);
    },
    schedule(payload) {
      const key = JSON.stringify(payload);
      if (key === lastKey) {
        // Reverting to the last requested payload drops any newer pending one.
        cancelPending();
        return;
      }
      cancelPending();
      timer = setTimeout(() => {
        timer = null;
        abortInFlight();
        lastKey = key;
        const current = new AbortController();
        controller = current;
        options
          .fetch(payload, current.signal)
          .then((result) => {
            if (!current.signal.aborted) options.onResult(result);
          })
          .catch(() => {
            // Best-effort preview: allow the same payload to be retried later.
            if (!current.signal.aborted && lastKey === key) lastKey = null;
          })
          .finally(() => {
            if (controller === current) controller = null;
          });
      }, debounceMs);
    },
    dispose() {
      cancelPending();
      abortInFlight();
    }
  };
}
