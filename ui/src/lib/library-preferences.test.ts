import { beforeEach, expect, it } from 'vitest';
import { preferenceKey, readPreferences, savePreferences } from './library-preferences';

beforeEach(() => localStorage.clear());

it('persists grouping and filters but not open resources', () => {
  const key = preferenceKey('owner@cognis.test');
  savePreferences(localStorage, key, new URLSearchParams('lib_group=conversation&lib_q=report&lib_item=dlv_report&lib_item_kind=deliverable'));
  expect(readPreferences(localStorage, key).toString()).toBe('lib_group=conversation&lib_q=report');
  expect(readPreferences(localStorage, preferenceKey('reader@cognis.test')).size).toBe(0);
  expect(readPreferences(localStorage, preferenceKey('owner@cognis.test', 'cognis')).size).toBe(0);
});

it('stores explicit cleared preferences and tolerates unavailable or malformed storage', () => {
  const key = preferenceKey('owner@cognis.test');
  savePreferences(localStorage, key, new URLSearchParams('lib_view=1'));
  expect(readPreferences(localStorage, key).get('lib_view')).toBe('1');
  localStorage.setItem(key, '{');
  expect(readPreferences(localStorage, key).size).toBe(0);
  const denied = { getItem: () => { throw new Error('Denied'); }, setItem: () => { throw new Error('Denied'); } } as unknown as Storage;
  expect(readPreferences(denied, key).size).toBe(0);
  expect(() => savePreferences(denied, key, new URLSearchParams())).not.toThrow();
});
