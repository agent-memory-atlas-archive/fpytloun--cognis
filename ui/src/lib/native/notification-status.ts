import { writable } from 'svelte/store';
export type NativeAuthorization = 'checking' | 'not-determined' | 'denied' | 'authorized' | 'provisional' | 'ephemeral' | 'unavailable';
export const nativeNotificationStatus = writable<{
  authorization: NativeAuthorization; message: string; errorDomain: string | null; errorCode: number | null;
}>({ authorization: 'checking', message: 'Reading macOS notification settings…', errorDomain: null, errorCode: null });

export function receiveNotificationStatus(command: Record<string, unknown>): void {
  if (!['not-determined', 'denied', 'authorized', 'provisional', 'ephemeral', 'unavailable'].includes(String(command.authorization))
    || typeof command.message !== 'string' || command.message.length > 1000
    || !(command.errorDomain === null || typeof command.errorDomain === 'string' && command.errorDomain.length <= 200)
    || !(command.errorCode === null || typeof command.errorCode === 'number' && Number.isSafeInteger(command.errorCode))) return;
  nativeNotificationStatus.set(command as unknown as {
    authorization: NativeAuthorization; message: string; errorDomain: string | null; errorCode: number | null;
  });
}
