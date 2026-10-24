import { get, writable, type Readable } from 'svelte/store';

export type WorkspaceDeviceClass = 'desktop' | 'tablet' | 'phone';
export type WorkspaceEntityKind = 'conversation' | 'agent' | 'task' | 'schedule' | 'attention' | 'artifact' | 'deliverable';
export type WorkspacePreset = 'center' | 'left' | 'right' | 'maximize' | 'restore';
export type WorkspaceSnapTarget = 'left' | 'right' | 'maximize';

export interface WorkspaceSafeRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface WorkspaceRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface WorkspaceWindowInput {
  kind: WorkspaceEntityKind;
  entityId: string;
  title: string;
  status?: string | null;
  canonicalHref: string;
  agentId?: string | null;
  ephemeral?: boolean;
}

export interface WorkspaceWindowState extends WorkspaceWindowInput {
  key: string;
  rect: WorkspaceRect;
  restoreRect: WorkspaceRect | null;
  minimized: boolean;
  zOrder: number;
  switcherOrder: number;
  refreshToken: number;
  focusRevision: number;
  resolvedConversationId?: string | null;
}

/** Opaque manager-owned gesture, never persisted or projected. */
export interface WorkspaceInteraction {
  readonly key: string;
  readonly id: symbol;
}

export interface WorkspaceInteractionPreview {
  rect: WorkspaceRect;
  snapTarget: WorkspaceSnapTarget | null;
}

interface GeometryInteraction {
  kind: 'move' | 'resize';
  expected: WorkspaceWindowState;
  startX: number;
  startY: number;
  origin: WorkspaceRect;
  pointerRatioX: number;
  titleOffsetY: number;
  detached: boolean;
  lastPointer: { x: number; y: number } | null;
  preview: WorkspaceInteractionPreview | null;
}

function sameRect(left: WorkspaceRect | null, right: WorkspaceRect | null): boolean {
  return left === right || !!left && !!right
    && left.x === right.x && left.y === right.y
    && left.width === right.width && left.height === right.height;
}

interface PersistedWorkspaceState {
  version: 1;
  windows: WorkspaceWindowState[];
}

export type WorkspaceOpenResult =
  | { status: 'opened' | 'focused'; key: string }
  | { status: 'capped'; limit: number; scope?: 'visible' | 'retained' | 'pinned-agents' }
  | { status: 'failed'; reason: string };
export type WorkspaceRestoreResult =
  | { status: 'restored'; key: string }
  | { status: 'capped'; limit: number };
export type WorkspaceSwitcherPlacement = 'before' | 'after';
export type WorkspaceDashboardActionResult =
  | { status: 'minimized'; count: number }
  | { status: 'empty'; count: 0 }
  | { status: 'restored'; count: number; capped: boolean; limit: number }
  | { status: 'inactive'; count: 0 };

const MIN_WIDTH = 360;
const MIN_HEIGHT = 320;
export const MAX_RETAINED_WORKSPACE_WINDOWS = 10;
export const WORKSPACE_SNAP_THRESHOLD = 28;
export const WORKSPACE_DOCK_GAP = 12;

export function workspaceSafeRectFromContent(
  bounds: { top: number; right: number; bottom: number; left: number },
  contentPadding: { top: number; right: number; bottom: number; left: number },
  shellTop: number,
  viewportWidth: number,
  horizontalPadding = 12,
): WorkspaceSafeRect {
  const top = Math.max(bounds.top + contentPadding.top, shellTop);
  const left = Math.max(bounds.left + contentPadding.left, 0) + horizontalPadding;
  const right = Math.min(bounds.right - contentPadding.right, viewportWidth) - horizontalPadding;
  const bottom = bounds.bottom - contentPadding.bottom;
  return {
    x: left,
    y: top,
    width: Math.max(0, right - left),
    height: Math.max(0, bottom - top),
  };
}

export function workspaceSafeRectWithDock(
  safe: WorkspaceSafeRect,
  dockHeight: number,
  gap = WORKSPACE_DOCK_GAP,
): WorkspaceSafeRect {
  if (dockHeight <= 0) return { ...safe };
  return {
    ...safe,
    height: Math.max(0, safe.height - dockHeight - gap),
  };
}

export function workspaceSafeRectAboveDock(
  safe: WorkspaceSafeRect,
  dockTop: number | null,
  gap = WORKSPACE_DOCK_GAP,
): WorkspaceSafeRect {
  if (dockTop === null) return { ...safe };
  const safeBottom = safe.y + safe.height;
  const reservedBottom = Math.min(safeBottom, dockTop - gap);
  return {
    ...safe,
    height: Math.max(0, reservedBottom - safe.y),
  };
}

export function dashboardWorkspaceStorageKey(userEmail: string | null | undefined): string {
  return `cognis.dashboard.workspace.v1:${encodeURIComponent(userEmail?.trim().toLowerCase() || 'anonymous')}`;
}

export function workspaceDeviceClass(width: number, coarsePointer: boolean): WorkspaceDeviceClass {
  if (width < 768) return 'phone';
  if (width < 1024 || coarsePointer) return 'tablet';
  return 'desktop';
}

export function workspaceCapacity(device: WorkspaceDeviceClass): number {
  return device === 'desktop' ? 5 : device === 'tablet' ? 2 : 1;
}

export function workspaceSnapTarget(
  clientX: number,
  clientY: number,
  safe: WorkspaceSafeRect,
  threshold = WORKSPACE_SNAP_THRESHOLD,
): WorkspaceSnapTarget | null {
  if (clientY <= safe.y + threshold) return 'maximize';
  if (clientX <= safe.x + threshold) return 'left';
  if (clientX >= safe.x + safe.width - threshold) return 'right';
  return null;
}

export function workspaceKey(kind: WorkspaceEntityKind, entityId: string): string {
  return `${kind}:${entityId}`;
}

export function activeWorkspaceWindowKey(
  windows: readonly WorkspaceWindowState[],
): string | null {
  return windows
    .filter((window) => !window.minimized)
    .reduce<WorkspaceWindowState | null>((active, window) => (
      !active || window.zOrder > active.zOrder ? window : active
    ), null)?.key ?? null;
}

export function workspaceKeyboardOwner(
  windows: readonly WorkspaceWindowState[],
  workspaceVisible: boolean,
  blockingOverlayActive: boolean,
): string | null {
  if (!workspaceVisible || blockingOverlayActive) return null;
  return activeWorkspaceWindowKey(windows);
}

export interface WorkspaceEscapeTarget {
  handleEscape(): boolean;
}

export function dispatchWorkspaceEscape(
  manager: WorkspaceManager,
  targets: Readonly<Record<string, WorkspaceEscapeTarget | undefined>>,
  workspaceVisible: boolean,
  blockingOverlayActive: boolean,
): boolean {
  if (!workspaceVisible || blockingOverlayActive) return false;
  const key = manager.focusedTopVisibleKey();
  if (!key) return false;
  if (targets[key]?.handleEscape()) return true;
  manager.close(key);
  return true;
}

export function clampWorkspaceRect(
  rect: WorkspaceRect,
  safe: WorkspaceSafeRect,
): WorkspaceRect {
  const minWidth = Math.min(MIN_WIDTH, safe.width);
  const minHeight = Math.min(MIN_HEIGHT, safe.height);
  const width = Math.min(safe.width, Math.max(minWidth, rect.width));
  const height = Math.min(safe.height, Math.max(minHeight, rect.height));
  return {
    x: Math.min(safe.x + safe.width - width, Math.max(safe.x, rect.x)),
    y: Math.min(safe.y + safe.height - height, Math.max(safe.y, rect.y)),
    width,
    height,
  };
}

export function defaultWorkspaceRect(
  safe: WorkspaceSafeRect,
  device: WorkspaceDeviceClass,
  index = 0,
): WorkspaceRect {
  if (device === 'tablet') return { ...safe };
  const width = Math.min(1280, safe.width * 0.8);
  const height = safe.height * 0.8;
  const offset = index * 24;
  return clampWorkspaceRect({
    x: safe.x + (safe.width - width) / 2 + offset,
    y: safe.y + (safe.height - height) / 2 + offset,
    width,
    height,
  }, safe);
}

export function workspacePresetRect(
  preset: Exclude<WorkspacePreset, 'restore'>,
  safe: WorkspaceSafeRect,
  device: WorkspaceDeviceClass,
): WorkspaceRect {
  if (preset === 'maximize') return { ...safe };
  if (preset === 'left') {
    return clampWorkspaceRect({ ...safe, width: safe.width / 2 }, safe);
  }
  if (preset === 'right') {
    return clampWorkspaceRect({
      ...safe,
      x: safe.x + safe.width / 2,
      width: safe.width / 2,
    }, safe);
  }
  return defaultWorkspaceRect(safe, device);
}

function cloneWindows(windows: WorkspaceWindowState[]): WorkspaceWindowState[] {
  return windows.map((window) => ({
    ...window,
    rect: { ...window.rect },
    restoreRect: window.restoreRect ? { ...window.restoreRect } : null,
  }));
}

function raiseWorkspaceWindows(
  windows: WorkspaceWindowState[],
  key: string,
  incrementFocusRevision: boolean,
): WorkspaceWindowState[] {
  const zOrderByKey = new Map(
    [
      ...windows
        .filter((window) => window.key !== key)
        .sort((left, right) => left.zOrder - right.zOrder),
      ...windows.filter((window) => window.key === key),
    ].map((window, index) => [window.key, index + 1]),
  );
  // Window array order owns stable mounted DOM identity. Visual stacking is
  // z-index-only, so focusing must not move a scrollable subtree in the DOM.
  return windows.map((window) => ({
    ...window,
    zOrder: zOrderByKey.get(window.key) ?? window.zOrder,
    focusRevision: incrementFocusRevision && window.key === key
      ? window.focusRevision + 1
      : window.focusRevision,
  }));
}

function isFiniteRect(value: unknown): value is WorkspaceRect {
  if (!value || typeof value !== 'object') return false;
  const rect = value as Record<string, unknown>;
  return ['x', 'y', 'width', 'height'].every((field) => (
    typeof rect[field] === 'number' && Number.isFinite(rect[field])
  ));
}

function optionalString(value: unknown): string | null {
  return typeof value === 'string' && value.length <= 500 ? value : null;
}

function safeCanonicalHref(value: unknown): string | null {
  if (
    typeof value !== 'string'
    || !value.startsWith('/')
    || value.startsWith('//')
    || value.includes('\\')
    || value.length > 1000
  ) return null;
  try {
    const base = new URL('https://cognis.invalid/');
    const parsed = new URL(value, base);
    if (parsed.origin !== base.origin) return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

function persistedWindow(
  value: unknown,
  safeRect: WorkspaceSafeRect,
  fallbackSwitcherOrder: number,
): WorkspaceWindowState | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  if (
    !(item.kind === 'conversation' || item.kind === 'agent' || item.kind === 'task'
      || item.kind === 'schedule' || item.kind === 'artifact' || item.kind === 'deliverable')
    || typeof item.entityId !== 'string'
    || !item.entityId
    || item.entityId.length > 500
    || typeof item.title !== 'string'
    || !item.title
    || item.title.length > 500
    || safeCanonicalHref(item.canonicalHref) === null
    || !isFiniteRect(item.rect)
  ) return null;
  const kind = item.kind;
  const entityId = item.entityId;
  const restoreRect = item.restoreRect === null
    ? null
    : isFiniteRect(item.restoreRect)
      ? clampWorkspaceRect(item.restoreRect, safeRect)
      : null;
  return {
    kind,
    entityId,
    key: workspaceKey(kind, entityId),
    title: item.title,
    status: optionalString(item.status),
    canonicalHref: safeCanonicalHref(item.canonicalHref)!,
    agentId: optionalString(item.agentId),
    rect: clampWorkspaceRect(item.rect, safeRect),
    restoreRect,
    minimized: item.minimized === true,
    zOrder: typeof item.zOrder === 'number' && Number.isFinite(item.zOrder)
      ? Math.max(1, Math.round(item.zOrder))
      : 1,
    switcherOrder: typeof item.switcherOrder === 'number' && Number.isFinite(item.switcherOrder)
      ? Math.max(1, Math.round(item.switcherOrder))
      : fallbackSwitcherOrder,
    refreshToken: 0,
    focusRevision: 1,
    resolvedConversationId: optionalString(item.resolvedConversationId),
  };
}

export function serializeWorkspaceWindows(
  windows: readonly WorkspaceWindowState[],
): string {
  const state: PersistedWorkspaceState = {
    version: 1,
    windows: cloneWindows(windows.filter((window) => !window.ephemeral)).map((window) => ({
      ...window,
      refreshToken: 0,
      focusRevision: 1,
    })),
  };
  return JSON.stringify(state);
}

export function parseWorkspaceWindows(
  serialized: string | null,
  safeRect: WorkspaceSafeRect,
): WorkspaceWindowState[] {
  if (!serialized) return [];
  try {
    const state = JSON.parse(serialized) as { version?: unknown; windows?: unknown };
    if (state.version !== 1 || !Array.isArray(state.windows)) return [];
    const byKey = new Map<string, { window: WorkspaceWindowState; storedIndex: number }>();
    for (const [storedIndex, value] of state.windows
      .slice(0, MAX_RETAINED_WORKSPACE_WINDOWS)
      .entries()) {
      const window = persistedWindow(value, safeRect, storedIndex + 1);
      if (window && !byKey.has(window.key)) byKey.set(window.key, { window, storedIndex });
    }
    const normalizedZOrder = [...byKey.values()]
      .sort((left, right) => left.window.zOrder - right.window.zOrder || left.storedIndex - right.storedIndex)
      .map(({ window, storedIndex }, index) => ({
        window: { ...window, zOrder: index + 1 },
        storedIndex,
      }));
    return normalizedZOrder
      .sort((left, right) => (
        left.window.switcherOrder - right.window.switcherOrder || left.storedIndex - right.storedIndex
      ))
      .map(({ window }, index) => ({ ...window, switcherOrder: index + 1 }));
  } catch {
    return [];
  }
}

export class WorkspaceManager implements Readable<WorkspaceWindowState[]> {
  private readonly closeGuards = new Map<string, () => boolean>();

  registerCloseGuard(key: string, guard: () => boolean): () => void {
    this.closeGuards.set(key, guard);
    return () => {
      if (this.closeGuards.get(key) === guard) this.closeGuards.delete(key);
    };
  }

  private readonly interactions = new Map<WorkspaceInteraction, GeometryInteraction>();
  private reconcilingSafeRect = false;
  private membership: {
    open(input: WorkspaceWindowInput): Promise<WorkspaceOpenResult>;
    close(key: string): Promise<void>;
    resolve(key: string, conversationId: string): Promise<void>;
  } | null = null;
  setMembershipActions(actions: WorkspaceManager['membership']): void { this.membership = actions; }
  async requestOpen(input: WorkspaceWindowInput): Promise<WorkspaceOpenResult> {
    if (this.membership && (input.kind === 'conversation' || input.kind === 'agent')) {
      return this.membership.open(input);
    }
    return this.open(input);
  }
  private readonly store = writable<WorkspaceWindowState[]>([]);
  // This is intentionally session-only. Any explicit window action clears it so the
  // dashboard control never revives a window after the workspace has changed.
  private dashboardSnapshot: { visibleKeys: string[]; focusedKey: string | null } | null = null;

  constructor(
    private device: WorkspaceDeviceClass,
    private safeRect: WorkspaceSafeRect,
    private readonly onClosed?: (window: WorkspaceWindowState) => void,
    private readonly onVisibilityChanged?: (
      window: WorkspaceWindowState,
      visible: boolean,
    ) => void,
  ) {
    this.store.subscribe((windows) => {
      for (const [token, session] of this.interactions) {
        const current = windows.find((window) => window.key === token.key);
        if (!current || current.minimized || current.kind !== session.expected.kind
            || current.entityId !== session.expected.entityId
            || current.resolvedConversationId !== session.expected.resolvedConversationId
            || !this.reconcilingSafeRect && (
              !sameRect(current.rect, session.expected.rect)
              || !sameRect(current.restoreRect, session.expected.restoreRect)
            )) {
          this.interactions.delete(token);
        } else {
          session.expected = current;
        }
      }
    });
  }

  subscribe = this.store.subscribe;

  snapshot(): WorkspaceWindowState[] {
    return cloneWindows(get(this.store));
  }

  persistentSnapshot(): WorkspaceWindowState[] {
    const current = get(this.store);
    const visibleKeys = new Set(this.dashboardSnapshot?.visibleKeys ?? []);
    return cloneWindows(current.map((window) => (
      visibleKeys.has(window.key) ? { ...window, minimized: false } : window
    )));
  }

  getSafeRect(): WorkspaceSafeRect {
    return { ...this.safeRect };
  }

  beginInteraction(
    key: string, kind: 'move' | 'resize', pointerX: number, pointerY: number,
  ): WorkspaceInteraction | null {
    const window = get(this.store).find((item) => item.key === key);
    if (!window || window.minimized) return null;
    for (const token of this.interactions.keys()) {
      if (token.key === key) this.interactions.delete(token);
    }
    const token = { key, id: Symbol(key) };
    this.interactions.set(token, {
      kind, expected: window, startX: pointerX, startY: pointerY,
      origin: { ...window.rect },
      pointerRatioX: Math.max(0, Math.min(1, (pointerX - window.rect.x) / window.rect.width)),
      titleOffsetY: Math.max(0, pointerY - window.rect.y),
      detached: window.restoreRect === null,
      lastPointer: null,
      preview: null,
    });
    return token;
  }

  isInteractionActive(token: WorkspaceInteraction): boolean {
    return this.interactions.has(token);
  }

  previewInteraction(
    token: WorkspaceInteraction, pointerX: number, pointerY: number,
  ): WorkspaceInteractionPreview | null {
    const session = this.interactions.get(token);
    if (!session || !Number.isFinite(pointerX) || !Number.isFinite(pointerY)) return null;
    let dx = pointerX - session.startX;
    let dy = pointerY - session.startY;
    if (session.kind === 'move' && !session.detached) {
      if (Math.hypot(dx, dy) < 16) return null;
      const source = clampWorkspaceRect(session.expected.restoreRect!, this.safeRect);
      session.origin = clampWorkspaceRect({
        ...source,
        x: pointerX - source.width * session.pointerRatioX,
        y: pointerY - session.titleOffsetY,
      }, this.safeRect);
      session.startX = pointerX;
      session.startY = pointerY;
      session.detached = true;
      dx = 0;
      dy = 0;
    }
    const rect = clampWorkspaceRect(session.kind === 'move'
      ? { ...session.origin, x: session.origin.x + dx, y: session.origin.y + dy }
      : { ...session.origin, width: session.origin.width + dx, height: session.origin.height + dy },
    this.safeRect);
    session.lastPointer = { x: pointerX, y: pointerY };
    session.preview = {
      rect,
      snapTarget: session.kind === 'move'
        ? workspaceSnapTarget(pointerX, pointerY, this.safeRect) : null,
    };
    return session.preview;
  }

  finishInteraction(token: WorkspaceInteraction, cancelled = false): void {
    const session = this.interactions.get(token);
    // A safe-area publication can race the component's next visual frame.
    // Recompute both geometry and snap at the canonical commit boundary.
    if (session?.lastPointer) {
      this.previewInteraction(token, session.lastPointer.x, session.lastPointer.y);
    }
    this.interactions.delete(token);
    if (!session?.preview) return;
    const previewRect = clampWorkspaceRect(session.preview.rect, this.safeRect);
    const snap = cancelled ? null : session.preview.snapTarget;
    this.clearDashboardSnapshot();
    this.store.update((windows) => windows.map((window) => window.key !== token.key ? window : {
      ...window,
      rect: snap ? workspacePresetRect(snap, this.safeRect, this.device) : previewRect,
      restoreRect: snap ? previewRect : null,
    }));
  }

  abandonInteraction(token: WorkspaceInteraction): void {
    this.interactions.delete(token);
  }

  hasDashboardSnapshot(): boolean {
    return this.dashboardSnapshot !== null;
  }

  hydrate(serialized: string | null): void {
    this.clearDashboardSnapshot();
    const visibleLimit = workspaceCapacity(this.device);
    const parsed = parseWorkspaceWindows(serialized, this.safeRect);
    const retainedVisibleKeys = new Set(
      parsed
        .filter((window) => !window.minimized)
        .sort((left, right) => right.zOrder - left.zOrder)
        .slice(0, visibleLimit)
        .map((window) => window.key),
    );
    const windows = parsed.map((window) => (
      !window.minimized && !retainedVisibleKeys.has(window.key)
        ? { ...window, minimized: true }
        : window
    ));
    this.store.set(windows);
    for (const window of windows) {
      if (!window.minimized) this.onVisibilityChanged?.(window, true);
    }
  }

  replaceProjection(windows: WorkspaceWindowState[]): void {
    const previous = get(this.store);
    const next = cloneWindows(windows).map((window) => ({
      ...window, rect: clampWorkspaceRect(window.rect, this.safeRect),
    }));
    const visible = new Set(next.filter((window) => !window.minimized)
      .sort((a, b) => b.zOrder - a.zOrder).slice(0, workspaceCapacity(this.device))
      .map((window) => window.key));
    for (const window of next) if (!visible.has(window.key)) window.minimized = true;
    for (const window of previous) {
      if (!next.some((item) => item.key === window.key)) this.onClosed?.(window);
      if (!window.minimized && !next.some((item) => item.key === window.key && !item.minimized)) {
        this.onVisibilityChanged?.(window, false);
      }
    }
    this.store.set(next);
    for (const window of next) {
      if (!window.minimized && !previous.some((item) => item.key === window.key && !item.minimized)) {
        this.onVisibilityChanged?.(window, true);
      }
    }
  }

  focusedTopVisibleKey(): string | null {
    return activeWorkspaceWindowKey(get(this.store));
  }

  setDevice(device: WorkspaceDeviceClass): void {
    if (device === this.device) return;
    this.device = device;
    this.reclamp();
    this.enforceVisibleCapacity();
  }

  setSafeRect(safeRect: WorkspaceSafeRect): void {
    const previousSafeRect = this.safeRect;
    this.safeRect = safeRect;
    this.reconcilingSafeRect = true;
    try {
      this.store.update((windows) => windows.map((window) => {
        const preset = (['maximize', 'left', 'right'] as const).find((candidate) => {
          const rect = workspacePresetRect(candidate, previousSafeRect, this.device);
          return (
            window.rect.x === rect.x
            && window.rect.y === rect.y
            && window.rect.width === rect.width
            && window.rect.height === rect.height
          );
        });
        return {
          ...window,
          rect: preset
            ? workspacePresetRect(preset, safeRect, this.device)
            : clampWorkspaceRect(window.rect, safeRect),
          restoreRect: window.restoreRect ? { ...window.restoreRect } : null,
        };
      }));
    } finally {
      this.reconcilingSafeRect = false;
    }
  }

  open(input: WorkspaceWindowInput): WorkspaceOpenResult {
    if (this.membership && (input.kind === 'conversation' || input.kind === 'agent')) {
      throw new Error('Retained membership requires awaiting requestOpen');
    }
    this.clearDashboardSnapshot();
    const key = workspaceKey(input.kind, input.entityId);
    const current = get(this.store);
    const existing = current.find((window) => window.key === key);
    if (existing) {
      if (existing.minimized) {
        const result = this.restore(key);
        if (result.status === 'capped') return result;
      } else {
        this.focus(key);
      }
      return { status: 'focused', key };
    }
    const visibleLimit = workspaceCapacity(this.device);
    const visibleCount = current.filter((window) => !window.minimized).length;
    if (visibleCount >= visibleLimit) return { status: 'capped', limit: visibleLimit };
    if (current.length >= MAX_RETAINED_WORKSPACE_WINDOWS) {
      return { status: 'capped', limit: MAX_RETAINED_WORKSPACE_WINDOWS };
    }

    let next = cloneWindows(current);
    let rect = defaultWorkspaceRect(this.safeRect, this.device, next.length);
    if (this.device === 'tablet' && next.length === 1) {
      next = next.map((window) => ({
        ...window,
        rect: workspacePresetRect('left', this.safeRect, this.device),
        restoreRect: null,
      }));
      rect = workspacePresetRect('right', this.safeRect, this.device);
    }
    next.push({
      ...input,
      key,
      status: input.status ?? null,
      rect,
      restoreRect: null,
      minimized: false,
      zOrder: next.length + 1,
      switcherOrder: Math.max(0, ...next.map((window) => window.switcherOrder)) + 1,
      refreshToken: 0,
      focusRevision: 1,
    });
    this.store.set(next);
    return { status: 'opened', key };
  }

  focus(key: string): void {
    this.clearDashboardSnapshot();
    this.store.update((windows) => raiseWorkspaceWindows(windows, key, true));
  }

  raise(key: string): void {
    this.clearDashboardSnapshot();
    this.store.update((windows) => raiseWorkspaceWindows(windows, key, false));
  }

  reorderSwitcher(
    sourceKey: string,
    targetKey: string,
    placement: WorkspaceSwitcherPlacement,
  ): boolean {
    this.clearDashboardSnapshot();
    const current = get(this.store);
    if (sourceKey === targetKey) return false;
    const source = current.find((window) => window.key === sourceKey);
    const target = current.find((window) => window.key === targetKey);
    if (!source || !target) return false;

    const ordered = [...current].sort((left, right) => left.switcherOrder - right.switcherOrder);
    const withoutSource = ordered.filter((window) => window.key !== sourceKey);
    const targetIndex = withoutSource.findIndex((window) => window.key === targetKey);
    if (targetIndex < 0) return false;
    withoutSource.splice(targetIndex + (placement === 'after' ? 1 : 0), 0, source);
    if (ordered.every((window, index) => window.key === withoutSource[index]?.key)) return false;

    const orderByKey = new Map(withoutSource.map((window, index) => [window.key, index + 1]));
    this.store.update((windows) => windows.map((window) => ({
      ...window,
      switcherOrder: orderByKey.get(window.key) ?? window.switcherOrder,
    })));
    return true;
  }

  async close(key: string): Promise<void> {
    if (this.closeGuards.get(key)?.() === false) return;
    const entry = get(this.store).find((item) => item.key === key);
    if (this.membership && entry && (entry.kind === 'conversation' || entry.kind === 'agent')) {
      return this.membership.close(key);
    }
    this.clearDashboardSnapshot();
    const closed = get(this.store).find((window) => window.key === key);
    this.store.update((windows) => windows.filter((window) => window.key !== key));
    if (closed) this.onClosed?.(closed);
  }

  /** Library-confirmed revision transitions replace identity without duplicating a revision window. */
  navigateDocument(
    key: string,
    input: WorkspaceWindowInput & { kind: 'artifact' | 'deliverable' },
  ): void {
    const current = get(this.store);
    const source = current.find((window) => window.key === key);
    if (!source || (source.kind !== 'artifact' && source.kind !== 'deliverable')) return;
    const nextKey = workspaceKey(input.kind, input.entityId);
    if (nextKey === key) return;
    this.clearDashboardSnapshot();
    const existing = current.find((window) => window.key === nextKey);
    this.store.set(current.filter((window) => window.key !== key).concat(existing ? [] : [{
      ...source, ...input, key: nextKey,
    }]));
    if (existing?.minimized) this.restore(nextKey);
    else this.focus(nextKey);
  }

  minimize(key: string): void {
    this.clearDashboardSnapshot();
    const minimized = get(this.store).find((window) => window.key === key);
    this.store.update((windows) => windows.map((window) => (
      window.key === key ? { ...window, minimized: true } : window
    )));
    if (minimized && !minimized.minimized) this.onVisibilityChanged?.(minimized, false);
  }

  restore(key: string): WorkspaceRestoreResult {
    this.clearDashboardSnapshot();
    const restored = get(this.store).find((window) => window.key === key);
    if (!restored) return { status: 'restored', key };
    if (!restored.minimized) {
      this.focus(key);
      return { status: 'restored', key };
    }
    const limit = workspaceCapacity(this.device);
    const visibleCount = get(this.store).filter((window) => !window.minimized).length;
    if (visibleCount >= limit) return { status: 'capped', limit };
    this.store.update((windows) => raiseWorkspaceWindows(
      windows.map((window) => (
        window.key === key ? { ...window, minimized: false } : window
      )),
      key,
      true,
    ));
    this.onVisibilityChanged?.(restored, true);
    return { status: 'restored', key };
  }

  move(key: string, x: number, y: number): void {
    this.clearDashboardSnapshot();
    this.patchRect(key, (rect) => ({ ...rect, x, y }));
  }

  resize(key: string, width: number, height: number): void {
    this.clearDashboardSnapshot();
    this.patchRect(key, (rect) => ({ ...rect, width, height }));
  }

  applyPreset(key: string, preset: WorkspacePreset): void {
    this.clearDashboardSnapshot();
    this.store.update((windows) => windows.map((window) => {
      if (window.key !== key) return window;
      if (preset === 'restore') {
        return window.restoreRect
          ? { ...window, rect: clampWorkspaceRect(window.restoreRect, this.safeRect), restoreRect: null }
          : window;
      }
      const rect = workspacePresetRect(preset, this.safeRect, this.device);
      return {
        ...window,
        rect,
        restoreRect: window.restoreRect ?? { ...window.rect },
      };
    }));
    this.focus(key);
  }

  restoreForDrag(
    key: string,
    pointerX: number,
    pointerY: number,
    pointerRatioX: number,
    titleOffsetY: number,
  ): WorkspaceRect | null {
    this.clearDashboardSnapshot();
    let restoredRect: WorkspaceRect | null = null;
    this.store.update((windows) => windows.map((window) => {
      if (window.key !== key || !window.restoreRect) return window;
      const source = clampWorkspaceRect(window.restoreRect, this.safeRect);
      restoredRect = clampWorkspaceRect({
        ...source,
        x: pointerX - source.width * pointerRatioX,
        y: pointerY - titleOffsetY,
      }, this.safeRect);
      return { ...window, rect: restoredRect, restoreRect: null };
    }));
    return restoredRect;
  }

  updateMetadata(
    key: string,
    metadata: { title: string; status?: string | null; agentId?: string | null },
  ): void {
    this.store.update((windows) => windows.map((window) => (
      window.key === key ? { ...window, ...metadata } : window
    )));
  }

  async setResolvedConversation(key: string, conversationId: string): Promise<void> {
    if (this.membership) return this.membership.resolve(key, conversationId);
    this.store.update((windows) => windows.map((window) => (
      window.key === key
        ? {
            ...window,
            resolvedConversationId: conversationId,
            canonicalHref: `/chat/${conversationId}`,
          }
        : window
    )));
  }

  invalidate(kind: Exclude<WorkspaceEntityKind, 'agent'>, entityId: string): void {
    this.store.update((windows) => windows.map((window) => (
      (
        (window.kind === kind && window.entityId === entityId)
        || (kind === 'conversation' && window.resolvedConversationId === entityId)
      )
        ? { ...window, refreshToken: window.refreshToken + 1 }
        : window
    )));
  }

  private patchRect(key: string, update: (rect: WorkspaceRect) => WorkspaceRect): void {
    this.store.update((windows) => windows.map((window) => (
      window.key === key
        ? { ...window, rect: clampWorkspaceRect(update(window.rect), this.safeRect), restoreRect: null }
        : window
    )));
  }

  showDashboard(): WorkspaceDashboardActionResult {
    const current = get(this.store);
    const visible = current.filter((window) => !window.minimized);
    if (visible.length === 0) {
      this.clearDashboardSnapshot();
      return { status: 'empty', count: 0 };
    }
    const snapshot = {
      visibleKeys: visible.map((window) => window.key),
      focusedKey: activeWorkspaceWindowKey(current),
    };
    this.dashboardSnapshot = snapshot;
    this.store.set(current.map((window) => (
      window.minimized ? window : { ...window, minimized: true }
    )));
    for (const window of visible) this.onVisibilityChanged?.(window, false);
    return { status: 'minimized', count: visible.length };
  }

  restoreDashboard(): WorkspaceDashboardActionResult {
    const snapshot = this.dashboardSnapshot;
    if (!snapshot) return { status: 'inactive', count: 0 };
    this.dashboardSnapshot = null;
    const current = get(this.store);
    const byKey = new Map(current.map((window) => [window.key, window]));
    const candidates = snapshot.visibleKeys
      .map((key) => byKey.get(key))
      .filter((window): window is WorkspaceWindowState => window?.minimized === true)
      .sort((left, right) => (
        (left.key === snapshot.focusedKey ? -1 : right.key === snapshot.focusedKey ? 1 : 0)
        || right.zOrder - left.zOrder
      ));
    const restore = candidates.slice(0, workspaceCapacity(this.device));
    if (restore.length === 0) return { status: 'inactive', count: 0 };
    const restoredKeys = new Set(restore.map((window) => window.key));
    const focusedKey = restoredKeys.has(snapshot.focusedKey ?? '') ? snapshot.focusedKey : restore[0].key;
    this.store.set(raiseWorkspaceWindows(
      current.map((window) => (
        restoredKeys.has(window.key) ? { ...window, minimized: false } : window
      )),
      focusedKey!,
      true,
    ));
    for (const window of restore) this.onVisibilityChanged?.(window, true);
    return {
      status: 'restored',
      count: restore.length,
      capped: restore.length < candidates.length,
      limit: workspaceCapacity(this.device),
    };
  }

  private clearDashboardSnapshot(): void {
    this.dashboardSnapshot = null;
  }

  private reclamp(): void {
    this.store.update((windows) => windows.map((window) => ({
      ...window,
      rect: clampWorkspaceRect(window.rect, this.safeRect),
      restoreRect: window.restoreRect
        ? clampWorkspaceRect(window.restoreRect, this.safeRect)
        : null,
    })));
  }

  private enforceVisibleCapacity(): void {
    const limit = workspaceCapacity(this.device);
    const visible = get(this.store)
      .filter((window) => !window.minimized)
      .sort((left, right) => right.zOrder - left.zOrder);
    const minimizedKeys = new Set(visible.slice(limit).map((window) => window.key));
    if (minimizedKeys.size === 0) return;
    this.store.update((windows) => windows.map((window) => (
      minimizedKeys.has(window.key) ? { ...window, minimized: true } : window
    )));
    for (const window of visible.slice(limit)) this.onVisibilityChanged?.(window, false);
  }
}
