import { describe, expect, it, vi } from 'vitest';
import { MetadataReadInvalidatedError, ReadFlights } from './read-flights';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

describe('metadata read flights', () => {
  it('coalesces only equivalent scopes, without retaining settled values or shared mutable objects', async () => {
    const flights = new ReadFlights();
    const pending = deferred<{ items: number[] }>();
    const load = vi.fn(() => pending.promise);
    const first = flights.run('owner-a:epoch-1:sidebar:active', load);
    const second = flights.run('owner-a:epoch-1:sidebar:active', load);
    const other = flights.run('owner-b:epoch-1:sidebar:active', load);
    const filtered = flights.run('owner-a:epoch-1:sidebar:archived', load);
    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(3);
    pending.resolve({ items: [1] });
    const [a, b] = await Promise.all([first, second, other, filtered]);
    a.items.push(2);
    expect(b.items).toEqual([1]);
    await flights.run('owner-a:epoch-1:sidebar:active', load);
    expect(load).toHaveBeenCalledTimes(4);
  });

  it('preserves independent cancellation and aborts the transport only after the last consumer leaves', async () => {
    const flights = new ReadFlights();
    const pending = deferred<string>();
    let transport!: AbortSignal;
    const load = vi.fn((signal: AbortSignal) => { transport = signal; return pending.promise; });
    const a = new AbortController();
    const b = new AbortController();
    const first = flights.run('same', load, a.signal);
    const second = flights.run('same', load, b.signal);
    await Promise.resolve();
    a.abort();
    await expect(first).rejects.toHaveProperty('name', 'AbortError');
    expect(transport.aborted).toBe(false);
    pending.resolve('fresh');
    await expect(second).resolves.toBe('fresh');
  });

  it('fences late invalidated results and cannot remove a replacement flight', async () => {
    const flights = new ReadFlights();
    const old = deferred<string>();
    const fresh = deferred<string>();
    const first = flights.run('same', () => old.promise);
    flights.invalidate();
    const second = flights.run('same', () => fresh.promise);
    old.resolve('stale');
    await expect(first).rejects.toBeInstanceOf(MetadataReadInvalidatedError);
    const third = flights.run('same', () => { throw new Error('duplicate'); });
    fresh.resolve('fresh');
    await expect(second).resolves.toBe('fresh');
    await expect(third).resolves.toBe('fresh');
  });

  it('releases rejected flights for retry and rejects an already cancelled consumer', async () => {
    const flights = new ReadFlights();
    await expect(flights.run('same', async () => { throw new Error('offline'); })).rejects.toThrow('offline');
    await expect(flights.run('same', async () => 'recovered')).resolves.toBe('recovered');
    const cancelled = AbortSignal.abort();
    const load = vi.fn();
    await expect(flights.run('same', load, cancelled)).rejects.toHaveProperty('name', 'AbortError');
    expect(load).not.toHaveBeenCalled();
  });
});
