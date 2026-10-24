import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AgentQuickProfileSwitcher from './AgentQuickProfileSwitcher.svelte';
import { tick } from 'svelte';
import type { RuntimeSelection } from '$lib/types/api';
const cleanSelection: RuntimeSelection = {
  revision: 1, profile_id: 'developer', profile_source: 'conversation',
  model: 'gpt-5', provider_id: 'openai', model_source: 'agent_profile',
  reasoning_effort: 'medium', reasoning_effort_source: 'agent_profile',
  fast_mode: false, fast_mode_source: 'agent_profile'
};

afterEach(cleanup);
// Happy DOM does not implement the native Popover API. Browser tests exercise
// opening, dismissal, positioning and draft concealment; expose its body here
// to test profile selection independently of that platform API.
function exposePanel(): void {
  screen.getByRole('dialog', { hidden: true }).removeAttribute('popover');
}
const agent = {
  default_agent_profile_id: 'developer',
  agent_profiles: {
    developer: { profile_id: 'developer' },
    worker: { profile_id: 'worker', quick_switch: true, quick_switch_index: 1 },
    architect: { profile_id: 'architect', quick_switch: true, quick_switch_index: 2 },
    critical: { profile_id: 'critical', quick_switch: true, quick_switch_index: 3 }
  }
};

describe('AgentQuickProfileSwitcher', () => {
  it('marks overrides and allows reselecting the current profile to restore it', async () => {
    const onSelect = vi.fn();
    const runtimeSelection = { ...cleanSelection, fast_mode_source: 'session_override' };
    const view = render(AgentQuickProfileSwitcher, { agent, profileId: 'developer', runtimeSelection, onSelect });
    exposePanel();
    expect(screen.getByLabelText('Profile settings overridden')).toBeVisible();
    expect(screen.getByText(/Fast mode: off/)).toBeVisible();
    await fireEvent.click(screen.getByRole('radio', { name: 'developer (Default)' }));
    expect(onSelect).toHaveBeenCalledWith('developer');
    await view.rerender({ agent, profileId: 'developer', runtimeSelection: cleanSelection, onSelect });
    expect(screen.queryByLabelText('Profile settings overridden')).toBeNull();
    await fireEvent.click(screen.getByRole('radio', { name: 'developer (Default)' }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
  it('restores a non-quick current profile by ID exactly once', async () => {
    const onSelect = vi.fn();
    const runtimeSelection = { ...cleanSelection, profile_id: 'senior', model_source: 'session_override' };
    render(AgentQuickProfileSwitcher, { agent, profileId: 'senior', runtimeSelection, onSelect });
    exposePanel();
    expect(screen.getByLabelText('Profile settings overridden')).toBeVisible();
    await fireEvent.click(screen.getByRole('button', { name: 'Restore profile settings' }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith('senior');
  });
  it('does not mark stale selections from another profile', () => {
    render(AgentQuickProfileSwitcher, { agent, profileId: 'critical',
      runtimeSelection: { ...cleanSelection, fast_mode_source: 'session_override' }, onSelect: vi.fn() });
    exposePanel();
    expect(screen.queryByLabelText('Profile settings overridden')).toBeNull();
  });
  it('selects with pointer and keyboard without optimistic state', async () => {
    const onSelect = vi.fn();
    render(AgentQuickProfileSwitcher, { agent, onSelect });
    exposePanel();
    const defaultRadio = screen.getByRole('radio', { name: 'developer (Default)' });
    expect(defaultRadio).toHaveAttribute('aria-checked', 'true');
    await fireEvent.click(screen.getByRole('radio', { name: 'architect' }));
    expect(onSelect).toHaveBeenLastCalledWith('architect');
    expect(defaultRadio).toHaveAttribute('aria-checked', 'true');
    await fireEvent.keyDown(defaultRadio, { key: 'End' });
    expect(onSelect).toHaveBeenLastCalledWith('critical');
    expect(screen.getByRole('radio', { name: 'critical' })).toHaveFocus();
  });

  it('keeps custom selections visible with no falsely selected stop', () => {
    render(AgentQuickProfileSwitcher, { agent, profileId: 'senior', onSelect: vi.fn() });
    exposePanel();
    expect(screen.getByText('senior · Custom')).toBeVisible();
    expect(screen.getAllByRole('radio').every((radio) => radio.getAttribute('aria-checked') === 'false')).toBe(true);
  });

  it('blocks busy and active-turn selections', async () => {
    const onSelect = vi.fn();
    render(AgentQuickProfileSwitcher, { agent, busy: true, onSelect });
    exposePanel();
    await fireEvent.click(screen.getByRole('radio', { name: 'architect' }));
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getAllByText('Switching…')).toHaveLength(2);
  });

  it('clears pending visuals on canonical profile and conversation changes', async () => {
    // Mirror the real parent: onSelect marks the request busy in the same turn.
    const onSelect = vi.fn(() => {
      void view.rerender({ agent, profileId: 'developer', conversationId: 'first', busy: true, onSelect });
    });
    const view = render(AgentQuickProfileSwitcher, { agent, profileId: 'developer', conversationId: 'first', onSelect });
    exposePanel();
    await tick();
    await fireEvent.click(screen.getByRole('radio', { name: 'critical' }));
    expect(screen.getByRole('radiogroup').style.getPropertyValue('--position')).toBe('3');
    await view.rerender({ agent, profileId: 'architect', conversationId: 'first', busy: true, onSelect });
    expect(screen.getByRole('radiogroup').style.getPropertyValue('--position')).toBe('2');
    await view.rerender({ agent, profileId: 'worker', conversationId: 'second', busy: true, onSelect });
    expect(screen.getByRole('radiogroup').style.getPropertyValue('--position')).toBe('1');
  });

  it('toggles a single quick profile on and back to the configured default', async () => {
    const onSelect = vi.fn();
    const toggleAgent = { default_agent_profile_id: 'developer', agent_profiles: {
      smart: { profile_id: 'smart', quick_switch: true }
    } };
    const view = render(AgentQuickProfileSwitcher, { agent: toggleAgent, onSelect });
    exposePanel();
    await fireEvent.click(screen.getByRole('switch'));
    expect(onSelect).toHaveBeenLastCalledWith('smart');
    await view.rerender({ agent: toggleAgent, profileId: 'smart', onSelect });
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
    await fireEvent.click(screen.getByRole('switch'));
    expect(onSelect).toHaveBeenLastCalledWith('developer');
  });
});
