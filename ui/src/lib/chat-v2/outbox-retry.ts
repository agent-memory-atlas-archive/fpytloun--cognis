// Retry policy for durable Chat v2 outbox sends.
//
// Sends are idempotent by `client_txn_id`, so a transient failure (offline,
// timeout, gateway or rate-limit error) is retried automatically with
// jittered exponential backoff. Permanent rejections (validation, payload too
// large, forbidden) are left for explicit user action instead of being
// re-sent forever.

export const OUTBOX_RETRY_BASE_MS = 2_000;
export const OUTBOX_RETRY_MAX_MS = 60_000;

const RETRYABLE_STATUSES = new Set([401, 408, 425, 429, 500, 502, 503, 504]);

/** True when a failed send may succeed if re-sent unchanged later. */
export function isRetryableSendError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') return true;
  if (error instanceof TypeError) return true;
  const status = typeof error === 'object' && error !== null && 'status' in error
    ? (error as { status?: unknown }).status
    : undefined;
  if (typeof status !== 'number' || status === 0) return true;
  return RETRYABLE_STATUSES.has(status) || status >= 500;
}

/**
 * Combine a message that failed without a durable outbox copy with whatever
 * the user has typed since. Nothing is dropped; repeated restores are no-ops.
 */
export function mergeFailedSendIntoDraft(failed: string, currentDraft: string): string {
  if (!failed.trim()) return currentDraft;
  if (!currentDraft.trim()) return failed;
  if (currentDraft.includes(failed)) return currentDraft;
  return `${failed}\n\n${currentDraft}`;
}

export function outboxRetryDelayMs(attempt: number, random: () => number = Math.random): number {
  const window = Math.min(OUTBOX_RETRY_MAX_MS, OUTBOX_RETRY_BASE_MS * 2 ** Math.max(0, attempt));
  return Math.round(window / 2 + random() * (window / 2));
}

/**
 * One pending retry timer per key (conversation). Scheduling while a timer is
 * pending is a no-op, so lifecycle triggers cannot stack retries.
 */
export class OutboxRetryScheduler {
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly attempts = new Map<string, number>();

  constructor(
    private readonly setTimer: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout> =
      (callback, delayMs) => setTimeout(callback, delayMs),
    private readonly clearTimer: (handle: ReturnType<typeof setTimeout>) => void =
      (handle) => clearTimeout(handle),
    private readonly random: () => number = Math.random,
  ) {}

  schedule(key: string, run: () => void): number | null {
    if (this.timers.has(key)) return null;
    const attempt = this.attempts.get(key) ?? 0;
    const delayMs = outboxRetryDelayMs(attempt, this.random);
    this.attempts.set(key, attempt + 1);
    const handle = this.setTimer(() => {
      this.timers.delete(key);
      run();
    }, delayMs);
    this.timers.set(key, handle);
    return delayMs;
  }

  /** Forget backoff state after a successful drain or when nothing remains. */
  reset(key: string): void {
    this.cancel(key);
    this.attempts.delete(key);
  }

  cancel(key: string): void {
    const handle = this.timers.get(key);
    if (handle !== undefined) this.clearTimer(handle);
    this.timers.delete(key);
  }

  cancelAll(): void {
    for (const handle of this.timers.values()) this.clearTimer(handle);
    this.timers.clear();
    this.attempts.clear();
  }

  pending(key: string): boolean {
    return this.timers.has(key);
  }
}
