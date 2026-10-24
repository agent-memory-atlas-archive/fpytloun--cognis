import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  user: { email: 'a@example.com' } as { email: string } | null,
  vapid: vi.fn(),
  subscribe: vi.fn(),
  unsubscribe: vi.fn(async () => undefined),
}));

vi.mock('$lib/stores/auth', () => ({
  auth: { getSnapshot: () => ({ user: mocks.user }) },
}));
vi.mock('$lib/api/client', () => ({
  api: {
    push: {
      vapidPublicKey: mocks.vapid,
      subscribe: mocks.subscribe,
      unsubscribe: mocks.unsubscribe,
    },
  },
}));

import {
  disableWebPushForCurrentDevice,
  enableWebPush,
  hasEnabledWebPush,
  reconcileWebPushSubscription,
  wantsWebPush,
} from './notifications';

const PUBLIC_KEY = 'BAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

function fakeSubscription(endpoint: string) {
  return {
    endpoint,
    options: { applicationServerKey: null },
    toJSON: () => ({ endpoint, keys: { p256dh: 'p', auth: 'a' } }),
    unsubscribe: vi.fn(async () => true),
  };
}

let current: ReturnType<typeof fakeSubscription> | null = null;
let browserSubscribe: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.localStorage.clear();
  mocks.user = { email: 'a@example.com' };
  mocks.vapid.mockResolvedValue({ enabled: true, public_key: PUBLIC_KEY });
  mocks.subscribe.mockReset().mockResolvedValue({ subscription_id: 's', enabled: true, gone: false });
  let counter = 0;
  current = null;
  browserSubscribe = vi.fn(async () => {
    counter += 1;
    current = fakeSubscription(`https://push.example/${counter}`);
    current.unsubscribe.mockImplementation(async () => {
      current = null;
      return true;
    });
    return current;
  });
  const registration = {
    pushManager: {
      getSubscription: vi.fn(async () => current),
      subscribe: browserSubscribe,
    },
  };
  vi.stubGlobal('PushManager', function PushManager() {});
  vi.stubGlobal('Notification', Object.assign(function Notification() {}, {
    permission: 'granted',
    requestPermission: vi.fn(async () => 'granted'),
  }));
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { ready: Promise.resolve(registration) },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe('web push lifecycle', () => {
  it('binds the opt-in to the user who enabled it', async () => {
    await expect(enableWebPush()).resolves.toMatchObject({ ok: true });
    expect(wantsWebPush()).toBe(true);
    mocks.user = { email: 'b@example.com' };
    expect(wantsWebPush()).toBe(false);
  });

  it('silently recreates a subscription the browser dropped', async () => {
    await enableWebPush();
    current = null;
    window.localStorage.removeItem('cognis_web_push_enabled');

    await expect(reconcileWebPushSubscription()).resolves.toBe(true);
    expect(browserSubscribe).toHaveBeenCalledTimes(2);
    expect(hasEnabledWebPush()).toBe(true);
  });

  it('replaces an endpoint the server reports as gone', async () => {
    await enableWebPush();
    mocks.subscribe
      .mockResolvedValueOnce({ subscription_id: 's', enabled: false, gone: true })
      .mockResolvedValueOnce({ subscription_id: 's2', enabled: true, gone: false });

    await expect(reconcileWebPushSubscription()).resolves.toBe(true);
    expect(current?.endpoint).toBe('https://push.example/2');
  });

  it('does not upload for another account when the user changes mid-reconcile', async () => {
    await enableWebPush();
    current = null;
    let releaseKey!: () => void;
    mocks.vapid.mockImplementationOnce(() => new Promise((resolve) => {
      releaseKey = () => resolve({ enabled: true, public_key: PUBLIC_KEY });
    }));
    mocks.subscribe.mockClear();

    const pending = reconcileWebPushSubscription();
    mocks.user = { email: 'b@example.com' };
    releaseKey();

    await expect(pending).resolves.toBe(false);
    expect(mocks.subscribe).not.toHaveBeenCalled();
  });

  it('reports not enabled when a replacement cannot be created', async () => {
    await enableWebPush();
    current = null;
    browserSubscribe.mockRejectedValueOnce(new DOMException('gesture required', 'NotAllowedError'));

    await expect(reconcileWebPushSubscription()).resolves.toBe(false);
    expect(hasEnabledWebPush()).toBe(false);
    // The intent survives, so the next reconcile retries.
    expect(wantsWebPush()).toBe(true);
  });

  it('disable during an in-flight reconcile is not undone', async () => {
    await enableWebPush();
    current = null;
    let releaseKey!: () => void;
    mocks.vapid.mockImplementationOnce(() => new Promise((resolve) => {
      releaseKey = () => resolve({ enabled: true, public_key: PUBLIC_KEY });
    }));
    mocks.subscribe.mockClear();

    const pending = reconcileWebPushSubscription();
    await disableWebPushForCurrentDevice();
    releaseKey();

    await expect(pending).resolves.toBe(false);
    expect(mocks.subscribe).not.toHaveBeenCalled();
    expect(wantsWebPush()).toBe(false);
    expect(hasEnabledWebPush()).toBe(false);
    browserSubscribe.mockClear();
    await expect(reconcileWebPushSubscription()).resolves.toBe(false);
    expect(browserSubscribe).not.toHaveBeenCalled();
  });

  it('explicit disable ends the intent even without a browser subscription', async () => {
    await enableWebPush();
    current = null;
    await disableWebPushForCurrentDevice();
    expect(wantsWebPush()).toBe(false);
    browserSubscribe.mockClear();
    await expect(reconcileWebPushSubscription()).resolves.toBe(false);
    expect(browserSubscribe).not.toHaveBeenCalled();
  });
});
