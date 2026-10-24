import { describe, expect, it, vi } from 'vitest';

import { ChatV2ApiError } from './api';
import {
  OUTBOX_RETRY_MAX_MS,
  OutboxRetryScheduler,
  isRetryableSendError,
  mergeFailedSendIntoDraft,
  outboxRetryDelayMs,
} from './outbox-retry';

describe('isRetryableSendError', () => {
  it('retries network, timeout, auth-recovery, throttling, and server failures', () => {
    expect(isRetryableSendError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isRetryableSendError(new ChatV2ApiError('timeout', { code: 'request_timeout', status: 0 }))).toBe(true);
    for (const status of [401, 408, 429, 500, 502, 503, 504]) {
      expect(isRetryableSendError(new ChatV2ApiError('x', { status }))).toBe(true);
    }
  });

  it('does not retry permanent rejections', () => {
    for (const status of [400, 403, 404, 409, 413, 422]) {
      expect(isRetryableSendError(new ChatV2ApiError('x', { status }))).toBe(false);
    }
  });
});

describe('OutboxRetryScheduler', () => {
  it('backs off with jitter and caps the delay', () => {
    expect(outboxRetryDelayMs(0, () => 0)).toBe(1_000);
    expect(outboxRetryDelayMs(0, () => 1)).toBe(2_000);
    expect(outboxRetryDelayMs(30, () => 1)).toBe(OUTBOX_RETRY_MAX_MS);
  });

  it('keeps one timer per key, grows the delay, and resets after success', () => {
    vi.useFakeTimers();
    try {
      const scheduler = new OutboxRetryScheduler(undefined, undefined, () => 1);
      const run = vi.fn();
      expect(scheduler.schedule('conv', run)).toBe(2_000);
      expect(scheduler.schedule('conv', run)).toBeNull();
      vi.advanceTimersByTime(2_000);
      expect(run).toHaveBeenCalledTimes(1);
      expect(scheduler.schedule('conv', run)).toBe(4_000);
      scheduler.reset('conv');
      expect(scheduler.pending('conv')).toBe(false);
      expect(scheduler.schedule('conv', run)).toBe(2_000);
      scheduler.cancelAll();
      vi.advanceTimersByTime(10_000);
      expect(run).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('mergeFailedSendIntoDraft', () => {
  it('keeps both the failed message and text typed since', () => {
    expect(mergeFailedSendIntoDraft('first', '')).toBe('first');
    expect(mergeFailedSendIntoDraft('first', 'second')).toBe('first\n\nsecond');
    expect(mergeFailedSendIntoDraft('first', 'first\n\nsecond')).toBe('first\n\nsecond');
    expect(mergeFailedSendIntoDraft('  ', 'second')).toBe('second');
  });
});
