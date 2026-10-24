import { beforeEach, expect, it } from 'vitest';
import 'fake-indexeddb/auto';
import { DocumentDrafts } from './document-drafts';
import { documentCoordination } from '$lib/document-coordination';

beforeEach(async () => {
  localStorage.clear();
  await documentCoordination().initialize();
  await documentCoordination().invalidate(false);
  await documentCoordination().verified('composite@cognis.test');
});
const input = () => ({ input_revision: crypto.randomUUID(), text: 'text',
  attachments: [], chat_mode: null });

it('keeps exact intent across reopen and tombstones it without stale-save resurrection', async () => {
  const drafts = new DocumentDrafts(), value = input();
  drafts.readComposite('draft');
  await drafts.writeComposite('draft', value);
  const sibling = new DocumentDrafts();
  expect(sibling.readComposite('draft')?.input_revision).toBe(value.input_revision);
  const captured = await drafts.persistComposite('draft', value);
  await drafts.consumeComposite(captured!, () => true);
  await sibling.writeComposite('draft', value);
  expect(new DocumentDrafts().readComposite('draft')?.consumed).toBe(true);
});

it('preserves the complete losing composite and refuses ABA consumption', async () => {
  const first = new DocumentDrafts(), sibling = new DocumentDrafts();
  first.readComposite('draft'); sibling.readComposite('draft');
  const a = input(), b = { ...input(), chat_mode: 'plan' as const };
  await first.writeComposite('draft', a);
  await sibling.writeComposite('draft', b);
  const values = Object.keys(localStorage).map((key) => localStorage.getItem(key)!);
  expect(values.some((value) => value.includes(b.input_revision) && value.includes('"plan"'))).toBe(true);
  const pinned = await first.persistComposite('draft', a);
  await first.writeComposite('draft', input());
  expect(await first.consumeComposite(pinned!, () => true)).toBe(false);
});

it('keeps queued newer intent canonical when older intent is consumed', async () => {
  const drafts = new DocumentDrafts(), a = input();
  drafts.readComposite('draft');
  const pinned = await drafts.persistComposite('draft', a);
  const b = { ...input(), text: 'newer B', chat_mode: 'plan' as const };
  const saving = drafts.writeComposite('draft', b);
  const consuming = drafts.consumeComposite(pinned!, () => true);
  await saving;
  expect(await consuming).toBe(false);
  expect(new DocumentDrafts().readComposite('draft')).toMatchObject({ ...b, consumed: false });
  expect(Object.keys(localStorage).some((key) => key.includes(':retained:'))).toBe(false);
});

it('does not overwrite queued newer intent when pinning older input', async () => {
  const drafts = new DocumentDrafts(), a = input();
  drafts.readComposite('draft');
  await drafts.writeComposite('draft', a);
  const b = { ...input(), text: 'newer B' };
  const saving = drafts.writeComposite('draft', b);
  const pinning = drafts.persistComposite('draft', a);
  await saving;
  expect(await pinning).toBeNull();
  expect(new DocumentDrafts().readComposite('draft')).toMatchObject({ ...b, consumed: false });
});

it('drains same-intent autosave before pinning and consuming exactly once', async () => {
  const drafts = new DocumentDrafts(), a = input();
  drafts.readComposite('draft');
  const saving = drafts.writeComposite('draft', a);
  const pinning = drafts.persistComposite('draft', a);
  await saving;
  const pinned = await pinning;
  expect(pinned?.input_revision).toBe(a.input_revision);
  const repeatedSave = drafts.writeComposite('draft', a);
  const consuming = drafts.consumeComposite(pinned!, () => true);
  await repeatedSave;
  expect(await consuming).toBe(true);
  await drafts.writeComposite('draft', a);
  expect(new DocumentDrafts().readComposite('draft')?.consumed).toBe(true);
});
