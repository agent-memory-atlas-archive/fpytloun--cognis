export type TimelineViewportMode = 'following' | 'paused';

export interface TimelineViewportAnchor {
  rowKey: string;
  offsetTop: number;
  scrollTop: number;
}

export interface TimelineViewportState {
  mode: TimelineViewportMode;
  anchor: TimelineViewportAnchor | null;
  scrollTop: number;
}

export interface TimelineViewportTransition {
  scopeKey: string;
  generation: number;
  state: TimelineViewportState;
}

const DEFAULT_STATE: TimelineViewportState = {
  mode: 'following',
  anchor: null,
  scrollTop: 0,
};

export class TimelineViewportStateStore {
  private readonly states = new Map<string, TimelineViewportState>();
  private active: TimelineViewportTransition | null = null;
  // Logical window ownership outlives DOM positioning, including child-view
  // hiding and return RAFs. Only a new load/owner or teardown invalidates it.
  private retainedWindow: { scopeKey: string; generation: number } | null = null;

  constructor(private readonly maxEntries = 32) {}

  save(scopeKey: string, state: TimelineViewportState): void {
    this.states.delete(scopeKey);
    this.states.set(scopeKey, {
      mode: state.mode,
      anchor: state.anchor ? { ...state.anchor } : null,
      scrollTop: state.scrollTop,
    });
    while (this.states.size > this.maxEntries) {
      const oldestScopeKey = this.states.keys().next().value;
      if (!oldestScopeKey) break;
      this.states.delete(oldestScopeKey);
    }
  }

  begin(scopeKey: string, generation: number): TimelineViewportTransition {
    this.invalidateWindow();
    const saved = this.states.get(scopeKey);
    if (saved) {
      this.states.delete(scopeKey);
      this.states.set(scopeKey, saved);
    }
    const transition = {
      scopeKey,
      generation,
      state: saved
        ? {
            mode: saved.mode,
            anchor: saved.anchor ? { ...saved.anchor } : null,
            scrollTop: saved.scrollTop,
          }
        : { ...DEFAULT_STATE },
    };
    this.active = transition;
    return transition;
  }

  isCurrent(scopeKey: string, generation: number): boolean {
    return this.active?.scopeKey === scopeKey && this.active.generation === generation;
  }

  settle(scopeKey: string, generation: number): boolean {
    if (!this.isCurrent(scopeKey, generation)) return false;
    this.active = null;
    return true;
  }

  establishWindow(scopeKey: string, generation: number): boolean {
    if (!this.isCurrent(scopeKey, generation) && !this.hasRetainedWindow(scopeKey, generation)) return false;
    this.retainedWindow = { scopeKey, generation };
    return true;
  }

  hasRetainedWindow(scopeKey: string, generation: number): boolean {
    return this.retainedWindow?.scopeKey === scopeKey && this.retainedWindow.generation === generation;
  }

  invalidateWindow(): void {
    this.retainedWindow = null;
  }

  invalidate(): void {
    this.active = null;
    this.invalidateWindow();
  }
}
