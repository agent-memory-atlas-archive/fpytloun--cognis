import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import AgentProfileSelect from './AgentProfileSelect.svelte';

afterEach(cleanup);

it('preserves a persisted profile while agent metadata is unavailable', () => {
  render(AgentProfileSelect, { agentId: 'reviewer', value: 'careful', agents: [] });
  expect(screen.getByRole('combobox')).toHaveValue('careful');
  expect(screen.getByRole('combobox')).toBeDisabled();
});
