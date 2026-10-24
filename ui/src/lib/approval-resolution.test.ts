import { describe, expect, it } from 'vitest';
import { isResolvedApprovalRejection } from './approval-resolution';

describe('approval resolution denial', () => {
  it('settles permanently rejected approval cards', () => {
    expect(isResolvedApprovalRejection({ resolved: true, decision: 'deny' })).toBe(true);
    expect(isResolvedApprovalRejection({ resolved: true, decision: 'cancel' })).toBe(true);
  });
  it('keeps unresolved, uncertain, and outage responses retryable', () => {
    for (const details of [null, {}, { resolved: false, decision: 'deny' },
      { resolved: true, decision: 'approve' }, { resolved: 'true', decision: 'deny' }]) {
      expect(isResolvedApprovalRejection(details)).toBe(false);
    }
  });
});
