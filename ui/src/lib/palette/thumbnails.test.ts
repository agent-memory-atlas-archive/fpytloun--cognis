import { describe, expect, it, vi } from 'vitest';
import { PaletteThumbnails } from './thumbnails';
import type { PaletteItem } from './model';
const image = (id: string): PaletteItem => ({ kind: 'artifact', id, title: `${id}.png`, href: `/library/artifact/${id}`,
  project_id: null, agent_id: null, status: null, format: 'image/png', size_bytes: 1024, updated_at: '' });
describe('palette image request budget', () => {
  it('signs at most two visible rasters concurrently and fences cleared jobs', async () => {
    const resolves: ((value: { url: string }) => void)[] = [];
    const sign = vi.fn(() => new Promise<{ url: string }>((resolve) => resolves.push(resolve)));
    const pool = new PaletteThumbnails(sign);
    const signal = new AbortController().signal;
    const jobs = ['first', 'second', 'third'].map((id) => pool.get(image(id), signal));
    expect(sign).toHaveBeenCalledTimes(2);
    pool.clear();
    resolves.forEach((resolve) => resolve({ url: '/signed-raster' }));
    expect(await Promise.all(jobs)).toEqual(['', '', '']);
    expect(sign).toHaveBeenCalledTimes(2);
  });
  it('does not fetch large originals or SVG', async () => {
    const sign = vi.fn();
    const pool = new PaletteThumbnails(sign);
    const signal = new AbortController().signal;
    expect(await pool.get({ ...image('large'), size_bytes: 10_000_000 }, signal)).toBe('');
    expect(await pool.get({ ...image('svg'), format: 'image/svg+xml' }, signal)).toBe('');
    expect(sign).not.toHaveBeenCalled();
  });
});
