import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/svelte';
import HookCard from './HookCard.svelte';
import type { NoticeTimelineItem } from '$lib/chat-v2/types';

function item(status: string): NoticeTimelineItem {
  return {
    id: 'hook:journal-run', kind: 'notice', level: 'info', sort_key: '0001',
    source_refs: [], stable: true, title: 'Consolidate memories',
    hook: { run_id: 'journal-run', hook_id: 'journal-hook', status,
      child_conversation_id: 'journal-child' }
  };
}
describe('HookCard', () => {
  it('shows retry progress and an actionable blocked state', async () => {
    const view = render(HookCard, { item: item('retrying') });
    expect(view.container.querySelector('.animate-spin')).not.toBeNull();
    expect(view.getByText('Continuing the unfinished session shortly…')).toBeTruthy();
    await view.rerender({ item: item('blocked') });
    expect(view.container.querySelector('.animate-spin')).toBeNull();
    expect(view.getByText('Execution stopped. Later eligible hooks can run normally.')).toBeTruthy();
  });
  it('shows progress and opens the internal session while running, then stops spinning', async () => {
    const notice = item('running');
    notice.hook = { ...notice.hook!, child_session_id: 'sess_hook_debrief' };
    const onViewSession = vi.fn();
    const view = render(HookCard, { item: notice, onViewSession });
    expect(view.container.querySelector('.animate-spin')).not.toBeNull();
    expect(view.getByRole('button', { name: 'Open session' })).toBeTruthy();
    await fireEvent.click(view.getByRole('button', { name: 'Open session' }));
    expect(onViewSession).toHaveBeenCalledWith('sess_hook_debrief');
    expect(view.queryByRole('link')).toBeNull();
    await view.rerender({ item: { ...notice, hook: { ...notice.hook!, status: 'completed' } }, onViewSession });
    expect(view.container.querySelector('.animate-spin')).toBeNull();
    expect(view.getByRole('button', { name: 'Open session' })).toBeTruthy();
    await fireEvent.click(view.getByRole('button', { name: 'Expand' }));
    await fireEvent.click(view.getByRole('button', { name: 'Open session' }));
    expect(onViewSession).toHaveBeenCalledTimes(2);
  });
  it('updates the source box without exposing an internal run chat', async () => {
    const view = render(HookCard, { item: item('dispatching') });
    expect(view.getByRole('status').textContent?.trim()).toBe('Starting');
    expect(view.queryByRole('link', { name: 'Open run' })).toBeNull();
    await view.rerender({ item: item('completed') });
    expect(view.getByRole('status').textContent?.trim()).toBe('completed');
    expect(view.getAllByRole('region', { name: 'Background hook' })).toHaveLength(1);
  });
  it('shows the captured outcome and distinguishes partial work without executing HTML', async () => {
    const notice = item('failed');
    notice.hook = { ...notice.hook!, outcome_partial: true, outcome_available: true,
      outcome: 'Updated **Research.md**.\n\n<script>alert("bad")</script>' };
    const view = render(HookCard, { item: notice });
    expect(view.container.querySelector('.chat-markdown')).toBeNull();
    await fireEvent.click(view.getByRole('button', { name: 'Expand' }));
    expect(view.getByText('Research.md')).toBeTruthy();
    expect(view.getByText(/Partial outcome/)).toBeTruthy();
    expect(view.container.querySelector('script')).toBeNull();
  });
  it('collapses multiline output into one summary row and labels the hook type', () => {
    const notice = item('completed');
    notice.hook = { ...notice.hook!, trigger: 'conversation_idle', outcome: 'First line.\n\nSecond line.' };
    const view = render(HookCard, { item: notice });
    expect(view.getByText('Idle hook')).toBeTruthy();
    expect(view.getByText('First line. Second line.')).toBeTruthy();
    expect(view.getByRole('button', { name: 'Expand' }).getAttribute('aria-expanded')).toBe('false');
    expect(view.container.querySelector('.chat-markdown')).toBeNull();
  });
  it('labels missing response rather than inventing an outcome', () => {
    const notice = item('completed');
    notice.hook = { ...notice.hook!, outcome_available: false };
    const view = render(HookCard, { item: notice });
    expect(view.getByText('No final response was available.')).toBeTruthy();
  });
  it('does not link internal execution even for a truncated legacy outcome', () => {
    const notice = item('completed');
    notice.hook = { ...notice.hook!, outcome: 'Projected result', result_truncated: true };
    const view = render(HookCard, { item: notice });
    expect(view.queryByRole('link')).toBeNull();
  });
  it('removes internal retain/replace markers from legacy outcome payloads', () => {
    const notice = item('completed');
    notice.hook = { ...notice.hook!,
      outcome: 'Updated Research.md. <!-- hook-handoff: replace --> <!-- hook-handoff: retain -->' };
    const view = render(HookCard, { item: notice });
    expect(view.getByText('Updated Research.md.')).toBeTruthy();
    expect(view.container.innerHTML).not.toContain('hook-handoff');
  });
});
