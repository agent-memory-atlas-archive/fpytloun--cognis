import { describe, expect, it } from 'vitest';
import { emptyHook, hookDefinition, hookTriggers } from './hooks';

describe('hook editing contracts', () => {
  it('creates an independent editable definition without registry metadata', () => {
    const original = {
      ...emptyHook(), hook_id: 'hook-editor', revision: 3, bundled: true,
      parameters: { interval: 10 }
    };
    const definition = hookDefinition(original);
    definition.parameters.interval = 20;
    expect(original.parameters.interval).toBe(10);
    expect(definition).not.toHaveProperty('hook_id');
    expect(definition).not.toHaveProperty('bundled');
  });
  it('covers all supported trigger boundaries', () => {
    expect(hookTriggers).toHaveLength(6);
    expect(hookTriggers).toContain('conversation_idle');
    expect(hookTriggers).toContain('first_user_message');
  });
});
