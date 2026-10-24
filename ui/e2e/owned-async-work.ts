/** Own test callbacks without exposing transport error messages/headers. */
export class OwnedAsyncWork {
  private pending = new Map<Promise<void>, string>();
  private eventWaiters = new Set<Promise<void>>();
  readonly failures: Array<{ label: string; phase: string; category: string }> = [];
  phase = 'body';
  private fail!: (error: Error) => void;
  readonly failure = new Promise<Error>(resolve => { this.fail = resolve; });

  run(label: string, action: () => Promise<unknown>): Promise<void> {
    const work = Promise.resolve().then(action).then(() => {}, error => {
      const message = String(error);
      const category = message.includes('context disposed') ? 'context-disposed'
        : /timeout|timed out/i.test(message) ? 'timeout'
        : message.includes('expect(') ? 'assertion' : 'callback-error';
      this.failures.push({ label, phase: this.phase, category });
      this.fail(new Error(`Owned fixture callback failed: ${label} (${category})`));
    });
    this.pending.set(work, label);
    void work.then(() => this.pending.delete(work));
    return work;
  }

  observe<T>(label: string, promise: Promise<T>): Promise<T> {
    const owned = this.run(label, () => promise);
    this.eventWaiters.add(owned);
    void owned.then(() => this.eventWaiters.delete(owned));
    return promise;
  }

  async guard<T>(work: Promise<T>): Promise<T> {
    return Promise.race([work, this.failure.then(error => { throw error; })]);
  }

  async drain(): Promise<void> {
    await Promise.all([...this.pending.keys()]);
  }

  async drainCallbacks(): Promise<void> {
    await Promise.all([...this.pending.keys()].filter(work => !this.eventWaiters.has(work)));
  }

  get pendingLabels(): string[] { return [...this.pending.values()]; }
}
