export const DEFAULT_API_REQUEST_TIMEOUT_MS = 30_000;

export class FetchTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
    this.name = 'FetchTimeoutError';
  }
}

export interface FetchWithTimeoutOptions {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

type SignalListener = {
  signal: AbortSignal;
  listener: () => void;
};

function abortController(controller: AbortController, signal: AbortSignal): void {
  if (controller.signal.aborted) return;
  controller.abort(signal.reason);
}

function mergeAbortSignals(signals: AbortSignal[]): { signal: AbortSignal; cleanup: () => void } {
  const activeSignals = signals.filter(Boolean);
  if (activeSignals.length === 1) {
    return { signal: activeSignals[0], cleanup: () => {} };
  }

  const controller = new AbortController();
  const listeners: SignalListener[] = [];

  for (const signal of activeSignals) {
    if (signal.aborted) {
      abortController(controller, signal);
      break;
    }
    const listener = () => abortController(controller, signal);
    signal.addEventListener('abort', listener, { once: true });
    listeners.push({ signal, listener });
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      for (const { signal, listener } of listeners) {
        signal.removeEventListener('abort', listener);
      }
    }
  };
}

/** True when a request body can be sent a second time unchanged. */
export function isReplayableBody(body: BodyInit | null | undefined): boolean {
  if (body === null || body === undefined) return true;
  if (typeof body === 'string') return true;
  if (typeof FormData !== 'undefined' && body instanceof FormData) return true;
  if (typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams) return true;
  if (typeof Blob !== 'undefined' && body instanceof Blob) return true;
  if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) return true;
  return false;
}

export function isFetchTimeoutError(error: unknown): error is FetchTimeoutError {
  return error instanceof FetchTimeoutError;
}

/** Deadline for an entire typed operation, including waits and body decoding.
 * Raw-response callers keep fetchWithTimeout's headers-only contract.
 */
export async function withRequestDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  options: { signal?: AbortSignal | null; timeoutMs?: number } = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_API_REQUEST_TIMEOUT_MS;
  const controller = new AbortController();
  const deadlineEnabled = Number.isFinite(timeoutMs) && timeoutMs > 0;
  const { signal, cleanup } = !deadlineEnabled && options.signal
    ? { signal: options.signal, cleanup: () => {} }
    : mergeAbortSignals(options.signal ? [options.signal, controller.signal] : [controller.signal]);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let listener: (() => void) | undefined;
  try {
    if (signal.aborted) throw signal.reason ?? new DOMException('Request aborted', 'AbortError');
    const cancelled = new Promise<never>((_, reject) => {
      listener = () => reject(signal.reason ?? new DOMException('Request aborted', 'AbortError'));
      if (signal.aborted) listener();
      else signal.addEventListener('abort', listener, { once: true });
      if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
        timer = setTimeout(() => controller.abort(new FetchTimeoutError(timeoutMs)), timeoutMs);
      }
    });
    return await Promise.race([operation(signal), cancelled]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    if (listener) signal.removeEventListener('abort', listener);
    cleanup();
  }
}

/** Decode a typed JSON body under the operation's cancellation owner. */
export async function readJsonWithSignal(response: Response, signal?: AbortSignal | null): Promise<unknown> {
  if (signal?.aborted) void response.body?.cancel(signal.reason).catch(() => {});
  signal?.throwIfAborted();
  if (!response.body) return response.json();
  const reader = response.body.getReader();
  const cancel = () => { void reader.cancel(signal?.reason).catch(() => {}); };
  signal?.addEventListener('abort', cancel, { once: true });
  const decoder = new TextDecoder();
  let text = '';
  try {
    signal?.throwIfAborted();
    while (true) {
      const { done, value } = await reader.read();
      signal?.throwIfAborted();
      if (done) break;
      text += decoder.decode(value, { stream: true });
    }
    return JSON.parse(text + decoder.decode());
  } finally {
    signal?.removeEventListener('abort', cancel);
    reader.releaseLock();
  }
}

/** Own an unread response while coordination/auth validation is still pending.
 * A locked reader owns its own cancellation through readJsonWithSignal.
 */
export function cancelResponseOnAbort(response: Response, signal?: AbortSignal | null): () => void {
  const cancel = () => { void response.body?.cancel(signal?.reason).catch(() => {}); };
  if (signal?.aborted) cancel();
  else signal?.addEventListener('abort', cancel, { once: true });
  return () => signal?.removeEventListener('abort', cancel);
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: FetchWithTimeoutOptions = {}
): Promise<Response> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const timeoutMs = options.timeoutMs ?? DEFAULT_API_REQUEST_TIMEOUT_MS;

  // Explicit opt-out for long-running uploads, downloads, audio synthesis, and
  // other calls that must not be aborted by the default API deadline.
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return fetchImpl(input, init);
  }

  const timeoutController = new AbortController();
  const { signal, cleanup } = mergeAbortSignals(
    init.signal ? [init.signal, timeoutController.signal] : [timeoutController.signal]
  );
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  const timeoutPromise = new Promise<never>((_resolve, reject) => {
    timeoutId = setTimeout(() => {
      const error = new FetchTimeoutError(timeoutMs);
      // Best-effort abort of the underlying fetch. Some WebKit/PWA fetches can
      // remain pending after abort, so the Promise.race below rejects directly
      // from this timer instead of relying on fetch to settle.
      timeoutController.abort(error);
      reject(error);
    }, timeoutMs);
  });

  try {
    return await Promise.race([fetchImpl(input, { ...init, signal }), timeoutPromise]);
  } catch (error) {
    if (timeoutController.signal.aborted && !init.signal?.aborted) {
      throw isFetchTimeoutError(error) ? error : new FetchTimeoutError(timeoutMs);
    }
    throw error;
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
    cleanup();
  }
}
