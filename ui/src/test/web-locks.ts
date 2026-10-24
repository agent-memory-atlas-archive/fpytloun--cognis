/** Deterministic FIFO Web Locks fixture shared by independently mounted stores. */
export class TestWebLocks {
  private tails = new Map<string, Promise<void>>();

  request<T>(name: string, options: LockOptions, action: (lock: Lock) => Promise<T>): Promise<T> {
    const previous = this.tails.get(name) ?? Promise.resolve();
    let release!: () => void;
    const finished = new Promise<void>((resolve) => { release = resolve; });
    this.tails.set(name, previous.then(() => finished));
    return new Promise<T>((resolve, reject) => {
      let entered = false;
      const abort = () => { if (!entered) reject(options.signal?.reason); };
      if (options.signal?.aborted) reject(options.signal.reason);
      options.signal?.addEventListener('abort', abort, { once: true });
      void previous.then(async () => {
        try {
          options.signal?.removeEventListener('abort', abort);
          if (options.signal?.aborted) { reject(options.signal.reason); return; }
          entered = true;
          resolve(await action({ name, mode: 'exclusive' } as Lock));
        } catch (error) { reject(error); }
        finally { release(); }
      });
    });
  }
}
