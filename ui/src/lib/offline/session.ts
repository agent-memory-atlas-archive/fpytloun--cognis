import { writable } from 'svelte/store';
import { auth } from '$lib/stores/auth';
import { documentCoordination, CoordinationUnavailableError } from '$lib/document-coordination';
import { attachmentUploads } from '$lib/chat-v2/attachment-uploads';
import { clearTimelineMemory } from '$lib/chat-v2/timeline-controller.svelte';
import { offlineCache } from './cache';
import { inspectRetainedData } from './quarantine';

export const deviceDataReady = writable(false);
export const deviceDataError = writable<string | null>(null);
let installed = false;
let transition = 0;

/** Historical export: session revocation no longer destroys retained work. */
export async function wipeAllDeviceData(): Promise<void> {
  attachmentUploads.reset();
  clearTimelineMemory();
  await offlineCache.setOwner(null);
}

/** Called before authenticated child pages mount; no storage permission prompts. */
export function installOfflineSession(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  let boundOwner: string | null = null;
  auth.subscribe((state) => {
    if (state.status !== 'authenticated' || !state.user?.email) return;
    const owner = state.user.email.trim().toLowerCase();
    if (owner === boundOwner) return;
    boundOwner = owner;
    const generation = ++transition;
    deviceDataReady.set(false);
    deviceDataError.set(null);
    void (async () => {
      const coordination = documentCoordination();
      const lease = coordination.capture();
      await lease.validate();
      if (typeof indexedDB === 'undefined') throw new CoordinationUnavailableError();
      if (!lease.owner?.endsWith(`\n${owner}`)) throw new Error('Account verification changed');
      await offlineCache.setOwner(coordination.storageName('offline-cache', lease));
      await lease.validate();
      await inspectRetainedData().catch(() => undefined);
      await lease.validate();
      if (generation === transition) deviceDataReady.set(true);
    })().catch((error) => {
      if (generation === transition) deviceDataError.set(error instanceof Error ? error.message : 'Local storage unavailable');
    });
  });
  auth.onAnonymous(() => {
    ++transition;
    boundOwner = null;
    deviceDataReady.set(false);
    deviceDataError.set(null);
    void wipeAllDeviceData();
  });
}
