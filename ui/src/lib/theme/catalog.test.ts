import { describe, expect, it } from 'vitest';
import { DEFAULT_THEME_FAMILY, THEME_FAMILIES, normalizeThemeFamily } from './catalog';
import { normalizeUserPreferences } from '$lib/user-preferences';

describe('bundled theme family contract', () => {
  it('exposes exactly the approved families with a Classic default', () => {
    expect(THEME_FAMILIES.map(({ id, name }) => [id, name])).toEqual([
      ['porcelain', 'Porcelain'], ['classic', 'Classic'], ['gruvbox', 'Gruvbox'], ['paper', 'Paper']
    ]);
    expect(DEFAULT_THEME_FAMILY).toBe('classic');
    expect(THEME_FAMILIES.find(({ id }) => id === 'classic')?.description).toContain('The default theme.');
  });

  it.each(THEME_FAMILIES)('preserves $id independently of appearance mode', ({ id }) => {
    for (const theme of ['light', 'dark', 'system']) {
      const preferences = normalizeUserPreferences({ display: { theme_family: id, theme } });
      expect(preferences.display).toMatchObject({ theme_family: id, theme });
    }
  });

  it.each([undefined, null, '', 'future-family', {}, 12])('normalizes invalid or absent family %s only', (value) => {
    expect(normalizeThemeFamily(value)).toBe('classic');
    const preferences = normalizeUserPreferences({
      display: { theme_family: value, theme: 'dark', language: 'cs-CZ', conversation_sidebar_dense: true },
      chat: { enter_to_send: false }, notifications: { include_content: false }
    });
    expect(preferences.display).toMatchObject({
      theme_family: 'classic', theme: 'dark', language: 'cs-CZ', conversation_sidebar_dense: true
    });
    expect(preferences.chat.enter_to_send).toBe(false);
    expect(preferences.notifications.include_content).toBe(false);
  });
});
