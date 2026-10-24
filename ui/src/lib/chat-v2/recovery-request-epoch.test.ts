import { expect, it } from 'vitest';
import { RecoveryRequestEpoch } from '../../../e2e/recovery-request-epoch';

it('rejects held old responses and only admits a request initiated in the new epoch', () => {
  const epoch = new RecoveryRequestEpoch<object>();
  const preDisconnect = {};
  epoch.initiated(preDisconnect);
  expect(epoch.accepts(preDisconnect)).toBe(false);
  epoch.begin();
  expect(epoch.accepts(preDisconnect)).toBe(false);
  epoch.initiated(preDisconnect);
  expect(epoch.accepts(preDisconnect)).toBe(false);
  const freshRequest = {};
  epoch.initiated(freshRequest);
  expect(epoch.accepts(freshRequest)).toBe(true);
  expect(epoch.accepts({})).toBe(false);
});
