import { describe, expect, it } from 'vitest';
import { DEFAULT_USER_PREFERENCES, normalizeUserPreferences } from './user-preferences';

describe('dashboard workspace window preference', () => {
  it('defaults legacy and invalid payloads to enabled', () => {
    expect(DEFAULT_USER_PREFERENCES.display.dashboard_workspace_windows).toBe(true);
    expect(normalizeUserPreferences({
      display: { theme: 'dark', language: 'en' },
      chat: {},
    }).display.dashboard_workspace_windows).toBe(true);
  });

  it('round-trips an explicit enabled value', () => {
    expect(normalizeUserPreferences({
      display: {
        theme: 'system',
        language: 'auto',
        dashboard_workspace_windows: true,
      },
      chat: {},
    }).display.dashboard_workspace_windows).toBe(true);
  });

  it('preserves an explicit disabled value', () => {
    expect(normalizeUserPreferences({
      display: { dashboard_workspace_windows: false },
    }).display.dashboard_workspace_windows).toBe(false);
  });
});

describe('conversation sidebar display preferences', () => {
  it('enables sections and preserves the current density for legacy payloads', () => {
    const preferences = normalizeUserPreferences({ display: {}, chat: {} });
    expect(preferences.display.conversation_sidebar_sections).toBe(true);
    expect(preferences.display.conversation_sidebar_dense).toBe(false);
  });

  it('preserves explicit sidebar preferences', () => {
    const preferences = normalizeUserPreferences({
      display: {
        conversation_sidebar_sections: false,
        conversation_sidebar_dense: true,
      },
    });
    expect(preferences.display.conversation_sidebar_sections).toBe(false);
    expect(preferences.display.conversation_sidebar_dense).toBe(true);
  });
});

describe('chat composer preference', () => {
  it('defaults legacy payloads to Enter-to-send', () => {
    expect(DEFAULT_USER_PREFERENCES.chat.enter_to_send).toBe(true);
    expect(normalizeUserPreferences({
      display: {},
      chat: {},
    }).chat.enter_to_send).toBe(true);
  });

  it('preserves an explicit Enter-as-newline preference', () => {
    expect(normalizeUserPreferences({
      display: {},
      chat: { enter_to_send: false },
    }).chat.enter_to_send).toBe(false);
  });
});

describe('notification content preference', () => {
  it('includes content by default for legacy preferences', () => {
    expect(normalizeUserPreferences({ display: {}, chat: {} }).notifications.include_content).toBe(true);
  });

  it('preserves the privacy-oriented opt-out', () => {
    expect(normalizeUserPreferences({
      notifications: { include_content: false },
    }).notifications.include_content).toBe(false);
  });
});
