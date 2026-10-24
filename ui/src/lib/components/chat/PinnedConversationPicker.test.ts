import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { conversationWorkspace } from '$lib/dashboard/conversation-workspace';
import Picker from './PinnedConversationPicker.svelte';

const mocks = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('$lib/api/client', () => ({
  api: { conversations: { list: mocks.list } }, asApiError: (cause: Error) => cause,
}));
beforeEach(() => { mocks.list.mockReset().mockResolvedValue({ items: [], has_more: false }); });
afterEach(cleanup);

it('stays pending throughout debounce and only shows empty after the matching response', async () => {
  render(Picker, { agentId: 'laforge', onOpen: () => {} });
  await screen.findByText('No matching conversations.');
  let resolve!: (response: { items: []; has_more: boolean }) => void;
  mocks.list.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'native' } });
  expect(screen.queryByText('No matching conversations.')).toBeNull();
  expect(screen.getByText('Loading…')).toBeInTheDocument();
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  expect(screen.queryByText('No matching conversations.')).toBeNull();
  resolve({ items: [], has_more: false });
  await screen.findByText('No matching conversations.');
  const calls = mocks.list.mock.calls.length;
  conversationWorkspace.setPosition(0.42);
  await new Promise((done) => setTimeout(done, 250));
  expect(mocks.list).toHaveBeenCalledTimes(calls);
  expect(screen.queryByText('Loading…')).toBeNull();
});

it('ignores a superseded response while the new query is pending', async () => {
  render(Picker, { agentId: 'laforge', onOpen: () => {} });
  await screen.findByText('No matching conversations.');
  let resolve!: (response: { items: []; has_more: boolean }) => void;
  mocks.list.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'first' } });
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'second' } });
  resolve({ items: [], has_more: false });
  expect(screen.queryByText('No matching conversations.')).toBeNull();
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(3));
  await screen.findByText('No matching conversations.');
});
