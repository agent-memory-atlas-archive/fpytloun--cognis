import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import NativeNotificationSettings from './NativeNotificationSettings.svelte';
import { nativeNotificationStatus, receiveNotificationStatus } from '$lib/native/notification-status';
const send = vi.hoisted(() => vi.fn());
vi.mock('$lib/native/host', () => ({ postNative: send }));
afterEach(() => { cleanup(); send.mockClear(); });
describe('native notification Settings', () => {
  it('reads OS status without asking permission and presents denied state, not browser unsupported', async () => {
    receiveNotificationStatus({ authorization: 'denied', message: 'Notifications denied by macOS.',
      errorDomain: 'UNErrorDomain', errorCode: 1 });
    render(NativeNotificationSettings);
    expect(send).toHaveBeenCalledWith('notification-settings', { action: 'status' });
    expect(screen.getByRole('status')).toHaveTextContent('denied');
    expect(screen.queryByText('unsupported')).toBeNull();
    expect(screen.getByText('UNErrorDomain (1)')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Open Notification Settings…' }));
    expect(send).toHaveBeenLastCalledWith('notification-settings', { action: 'show' });
    expect(send.mock.calls.some(([, payload]) => payload.action === 'enable')).toBe(false);
  });
  it('keeps an undetermined status distinct from unavailable and validates incoming fields', () => {
    receiveNotificationStatus({ authorization: 'not-determined', message: 'Use the native action.',
      errorDomain: null, errorCode: null });
    render(NativeNotificationSettings);
    expect(screen.getByRole('button', { name: 'Enable Notifications…' })).toBeInTheDocument();
    receiveNotificationStatus({ authorization: 'unsupported', message: 'Incorrect browser fallback',
      errorDomain: null, errorCode: null });
    let value; const stop = nativeNotificationStatus.subscribe((state) => { value = state.authorization; });
    stop(); expect(value).toBe('not-determined');
  });
});
