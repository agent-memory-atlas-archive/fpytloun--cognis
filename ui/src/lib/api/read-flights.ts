export class MetadataReadInvalidatedError extends Error {
  constructor() { super('Metadata changed while the read was pending.'); }
}

export type MetadataInvalidationOwner = 'transport' | 'refresh';

/** In-flight metadata reads only: no settled values or authorization decisions. */
export class ReadFlights {
  private flights = new Map<string, {
    controller: AbortController; promise: Promise<unknown>; users: number;
    invalidationOwner: MetadataInvalidationOwner;
  }>();

  invalidate(options: { preserveRefreshOwned?: boolean } = {}): void {
    for (const [key, flight] of this.flights) {
      // Realtime hints queue one trailing refresh at the owning controller.
      // Mutation/account invalidation still uses the unconditional default.
      if (options.preserveRefreshOwned && flight.invalidationOwner === 'refresh') continue;
      this.flights.delete(key);
      flight.controller.abort(new MetadataReadInvalidatedError());
    }
  }

  run<T>(
    key: string, load: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal | null,
    invalidationOwner: MetadataInvalidationOwner = 'transport',
  ): Promise<T> {
    if (signal?.aborted) return Promise.reject(signal.reason);
    let flight = this.flights.get(key);
    if (!flight) {
      const controller = new AbortController();
      flight = {
        controller, promise: Promise.resolve().then(() => load(controller.signal)), users: 0,
        invalidationOwner,
      };
      this.flights.set(key, flight);
      const current = flight;
      const remove = () => {
        if (this.flights.get(key) === current) this.flights.delete(key);
      };
      void flight.promise.then(remove, remove);
    }
    const current = flight;
    current.users++;
    return new Promise<T>((resolve, reject) => {
      let settled = false;
      const finish = (error: unknown, value?: T) => {
        if (settled) return;
        settled = true;
        signal?.removeEventListener('abort', abort);
        current.users--;
        if (!current.users) {
          if (this.flights.get(key) === current) this.flights.delete(key);
          current.controller.abort();
        }
        if (error !== undefined) reject(error);
        else resolve(structuredClone(value as T));
      };
      const abort = () => finish(signal?.reason ?? new DOMException('Aborted', 'AbortError'));
      signal?.addEventListener('abort', abort, { once: true });
      void current.promise.then(
        value => finish(current.controller.signal.aborted
          ? current.controller.signal.reason : undefined, value as T),
        error => finish(error),
      );
    });
  }
}

export const metadataReadFlights = new ReadFlights();
