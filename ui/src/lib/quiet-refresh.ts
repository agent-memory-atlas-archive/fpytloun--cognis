export const REFRESH_STALE_AFTER_MS = 60_000;

/** One continuous failure interval per scope; retries do not restart it. */
export class QuietRefresh {
  private scope: string | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stale = false;

  constructor(private readonly changed: (stale: boolean) => void) {}

  update(scope: string, failed: boolean): void {
    if (scope !== this.scope) {
      this.reset();
      this.scope = scope;
    }
    if (!failed) {
      this.reset();
    } else if (!this.timer && !this.stale) {
      this.timer = setTimeout(() => {
        this.timer = null;
        this.stale = true;
        this.changed(true);
      }, REFRESH_STALE_AFTER_MS);
    }
  }

  dispose(): void { this.reset(); }

  private reset(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.stale) this.changed(false);
    this.stale = false;
  }
}
