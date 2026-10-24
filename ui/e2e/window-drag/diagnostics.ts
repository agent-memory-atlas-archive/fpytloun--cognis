import { performance } from 'node:perf_hooks';
import { writeFile } from 'node:fs/promises';
import type { Page, Request, TestInfo } from '@playwright/test';

const LIMIT = 200;
const states = new WeakMap<Page, {
  started: number;
  requests: number;
  responses: number;
  finished: number;
  failed: number;
  dropped: number;
  snapshots: Record<string, { requested: number; fulfilled: number; finished: number; failed: number }>;
  events: Array<Record<string, unknown>>;
}>();

/** Opt-in synthetic-fixture diagnostics, never production instrumentation. */
export async function startDiagnostics(page: Page): Promise<void> {
  if (process.env.DRAG_DIAGNOSTIC !== '1') return;
  const state = { started: performance.now(), requests: 0, responses: 0, finished: 0, failed: 0, dropped: 0,
    snapshots: {} as Record<string, { requested: number; fulfilled: number; finished: number; failed: number }>,
    events: [] as Array<Record<string, unknown>> };
  states.set(page, state);
  const flights = new WeakMap<Request, { id: number; started: number }>();
  const record = (event: Record<string, unknown>) => {
    if (state.events.length < LIMIT) state.events.push({ ms: performance.now() - state.started, ...event });
    else state.dropped++;
  };
  const path = (url: string) => {
    const parsed = new URL(url);
    return parsed.origin === 'http://127.0.0.1:4178' ? parsed.pathname.slice(0, 180) : 'blocked-external';
  };
  const snapshot = (request: Request) => {
    const key = new URL(request.url()).pathname.match(/\/conversations\/(drag-chat-[0-4])\/snapshot$/)?.[1];
    if (!key) return null;
    return state.snapshots[key] ??= { requested: 0, fulfilled: 0, finished: 0, failed: 0 };
  };
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) record({
      kind: 'console', level: message.type(), message: message.text().slice(0, 300),
    });
  });
  page.on('pageerror', (error) => record({ kind: 'pageerror', name: error.name, message: error.message.slice(0, 300) }));
  page.on('request', (request) => {
    if (!new URL(request.url()).pathname.startsWith('/api/')) return;
    const id = ++state.requests;
    const counter = snapshot(request);
    if (counter) counter.requested++;
    flights.set(request, { id, started: performance.now() });
    record({ kind: 'request', id, path: path(request.url()), method: request.method() });
  });
  page.on('response', (response) => {
    const flight = flights.get(response.request());
    if (!flight) return;
    state.responses++;
    const counter = snapshot(response.request());
    if (counter && response.ok()) counter.fulfilled++;
    record({ kind: 'response', id: flight.id, path: path(response.url()), status: response.status(),
      elapsedMs: performance.now() - flight.started });
  });
  page.on('requestfailed', (request) => {
    const flight = flights.get(request);
    if (!flight) return;
    state.failed++;
    const counter = snapshot(request);
    if (counter) counter.failed++;
    record({ kind: 'requestfailed', id: flight.id, path: path(request.url()),
      elapsedMs: performance.now() - flight.started });
  });
  page.on('requestfinished', (request) => {
    const flight = flights.get(request);
    if (!flight) return;
    state.finished++;
    const counter = snapshot(request);
    if (counter) counter.finished++;
    record({ kind: 'requestfinished', id: flight.id, path: path(request.url()),
      elapsedMs: performance.now() - flight.started });
  });
  // Never allow the diagnostic to reach a service or an external asset host.
  // The test's later API routes fulfil all fixture API traffic synthetically.
  await page.route('**/*', (route) => new URL(route.request().url()).origin === 'http://127.0.0.1:4178'
    ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(() => {
    const events: Array<Record<string, unknown>> = [];
    const counts: Record<string, number> = {};
    const identities = new WeakMap<object, number>();
    let nextIdentity = 0;
    let dropped = 0;
    const scopes: Record<string, { phase: string; counts: Record<string, number>; activeReferences: number }> = {};
    const owners = { acquires: 0, creates: 0, invalidations: 0, memoryClears: 0 };
    const identity = (value?: object) => {
      if (!value) return null;
      if (!identities.has(value)) identities.set(value, ++nextIdentity);
      return identities.get(value);
    };
    Object.assign(globalThis, {
      __dragOwnerClear: () => { owners.memoryClears++; },
      __dragLifecycle: (kind: string, scope: { key: string }, controller?: object) => {
        counts[kind] = (counts[kind] ?? 0) + 1;
        if (Object.keys(scopes).length < 6 || scopes[scope.key]) {
          const state = scopes[scope.key] ??= { phase: 'idle', counts: {}, activeReferences: 0 };
          state.counts[kind] = (state.counts[kind] ?? 0) + 1;
          if (kind === 'controller-retain') state.activeReferences++;
          if (kind === 'controller-release') state.activeReferences--;
          if (['controller-load', 'hydrate-start', 'hydrate-finished', 'snapshot-dispatch', 'snapshot-received',
            'projection-yielded', 'controller-ready', 'controller-error', 'controller-invalidate'].includes(kind)) state.phase = kind;
        }
        if (kind === 'canonical-acquire') owners.acquires++;
        if (kind === 'controller-create') owners.creates++;
        if (kind === 'controller-invalidate') owners.invalidations++;
        if (events.length < 200) events.push({
          kind, ms: performance.now(), scopeKey: scope.key.slice(0, 120),
          scopeIdentity: identity(scope), controllerIdentity: identity(controller),
        });
        else dropped++;
      },
      __dragDiagnosticSnapshot: () => ({
        counts: { ...counts }, events: [...events], dropped, scopes, owners,
        viewports: [...document.querySelectorAll<HTMLElement>('[data-window-key]')].slice(0, 5).map((panel) => {
          const viewport = panel.querySelector<HTMLElement>('[data-testid="scoped-timeline-viewport"]');
          return {
            key: panel.dataset.windowKey,
            message119: [...panel.querySelectorAll('p')].filter((node) => node.textContent === 'Synthetic message 119').length,
            loading: panel.textContent?.includes('Loading timeline…'),
            scrollTop: viewport?.scrollTop, contentHeight: viewport?.scrollHeight,
          };
        }),
      }),
    });
  });
}

/** Runs even if navigation/readiness throws, before pointerdown or CDP tracing. */
export async function saveDiagnostics(page: Page, testInfo: TestInfo): Promise<void> {
  const state = states.get(page);
  if (!state) return;
  let browser: unknown = { unavailable: true };
  if (!page.isClosed()) {
    browser = await Promise.race([
      page.evaluate(() => {
        const snapshot = (globalThis as typeof globalThis & { __dragDiagnosticSnapshot?: () => unknown }).__dragDiagnosticSnapshot;
        return snapshot?.() ?? { instrumentationMissing: true };
      }).catch(() => ({ unavailable: true })),
      new Promise((resolve) => setTimeout(() => resolve({ captureDeadline: true }), 1000)),
    ]);
  }
  const body = Buffer.from(JSON.stringify({
      diagnosticOnly: true, status: testInfo.status,
      requests: state.requests, responses: state.responses, finished: state.finished, failed: state.failed,
      snapshots: Object.fromEntries(Object.entries(state.snapshots).map(([key, value]) =>
        [key, { ...value, pending: value.requested - value.finished - value.failed }])),
      dropped: state.dropped, events: state.events, browser,
    }, null, 2));
  await writeFile(testInfo.outputPath('initialization-diagnostic.json'), body);
  await testInfo.attach('initialization-diagnostic', {
    contentType: 'application/json', body,
  });
}
