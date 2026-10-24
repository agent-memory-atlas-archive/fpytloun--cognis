import { describe, expect, it } from 'vitest';
import { reconcileTimelineMembership } from '$lib/chat-page';

const rows = (...ids: string[]) => ids.map(id => ({ id }));

describe('view-local identity window reconciliation', () => {
  it('does not count concurrent live appends as prepended history', () => {
    const before = rows('a', 'b', 'c', 'd');
    const after = rows('older', 'a', 'b', 'c', 'd', 'live');
    expect(reconcileTimelineMembership({ start: 1, end: null }, before, after))
      .toEqual({ start: 2, end: 5 });
  });
  it('reveals new older rows only for the requesting view already at the start', () => {
    const before = rows('a', 'b');
    const after = rows('older', 'a', 'b', 'live');
    expect(reconcileTimelineMembership({ start: 0, end: 2 }, before, after, true))
      .toEqual({ start: 0, end: 3 });
    expect(reconcileTimelineMembership({ start: 0, end: 2 }, before, after, false))
      .toEqual({ start: 1, end: 3 });
  });
  it('maps surviving identities across removal and ordering changes', () => {
    expect(reconcileTimelineMembership({ start: 1, end: 3 },
      rows('a', 'b', 'c', 'd'), rows('c', 'a', 'd')))
      .toEqual({ start: 0, end: 1 });
  });
});
