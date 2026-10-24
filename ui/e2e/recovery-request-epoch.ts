/** Fixture-only identity fence: response arrival time never admits an old request. */
export class RecoveryRequestEpoch<T extends object> {
  private started = false;
  private readonly seen = new WeakSet<T>();
  private readonly eligible = new WeakSet<T>();

  begin(): void { this.started = true; }

  initiated(request: T): void {
    if (this.seen.has(request)) return;
    this.seen.add(request);
    if (this.started) this.eligible.add(request);
  }

  accepts(request: T): boolean { return this.eligible.has(request); }
}
