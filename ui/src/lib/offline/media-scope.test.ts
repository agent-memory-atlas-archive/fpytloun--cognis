import { describe, expect, it } from 'vitest';
import { MediaScopes } from './media-scope';
import source from '../../service-worker.ts?raw';

describe('worker account/epoch media projection', () => {
  it('unknown/restarted clients cannot select a legacy cache', () => {
    expect(new MediaScopes().scope('unbound')).toBeUndefined();
    expect(source).not.toContain('openCacheWithTimeout(MEDIA_CACHE)');
    expect(source).not.toContain('caches.delete(MEDIA_CACHE)');
    expect(source).toContain('if (!scope) return fetch(request)');
  });
  it('separates account and epoch cache keys and revokes stale in-flight writes', () => {
    const scopes = new MediaScopes();
    scopes.bind('a', 'https://server.invalid\naccount-a', 'first');
    scopes.bind('b', 'https://server.invalid\naccount-b', 'first');
    const first = scopes.scope('a')!;
    expect(scopes.cache(first)).not.toBe(scopes.cache(scopes.scope('b')!));
    scopes.revoke();
    expect(scopes.current('a', first)).toBe(false);
    scopes.bind('a', first.owner, 'second');
    expect(scopes.current('a', first)).toBe(false);
    expect(scopes.cache(first)).not.toBe(scopes.cache(scopes.scope('a')!));
  });
});
