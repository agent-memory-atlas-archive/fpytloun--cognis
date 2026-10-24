import { afterEach, describe, expect, it, vi } from 'vitest';
import { CHAT_STORAGE_KEYS } from '$lib/chat-page';
import type { Agent } from '$lib/types/api';
import { preferredNewChatAgentId } from './new-chat-agent';

const agents = [
  { agent_id: 'first', agent_type: 'primary', status: 'active' },
  { agent_id: 'previous', agent_type: 'primary', status: 'active' },
  { agent_id: 'inactive', agent_type: 'primary', status: 'suspended' },
] as Agent[];

afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('preferredNewChatAgentId', () => {
  it('prefers the current chat or explicit agent over stored selection', () => {
    localStorage.setItem(CHAT_STORAGE_KEYS.selectedAgent, JSON.stringify(['first']));
    expect(preferredNewChatAgentId(agents, ['previous'])).toBe('previous');
  });

  it.each(['previous', JSON.stringify(['previous'])])('reads the Chat app selection %s', (stored) => {
    localStorage.setItem(CHAT_STORAGE_KEYS.selectedAgent, stored);
    expect(preferredNewChatAgentId(agents)).toBe('previous');
  });

  it.each(['inactive', 'removed', JSON.stringify(['first', 'previous'])])('ignores unavailable or ambiguous selection %s', (stored) => {
    localStorage.setItem(CHAT_STORAGE_KEYS.selectedAgent, stored);
    expect(preferredNewChatAgentId(agents, [], 'previous')).toBe('previous');
  });

  it('retains previous dialog selection when eligible and falls back safely', () => {
    expect(preferredNewChatAgentId(agents, ['removed', 'previous'])).toBe('previous');
    expect(preferredNewChatAgentId(agents, ['inactive'])).toBe('first');
    expect(preferredNewChatAgentId([])).toBe('');
  });

  it('works when browser storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Storage blocked'); });
    expect(preferredNewChatAgentId(agents)).toBe('first');
  });
});
