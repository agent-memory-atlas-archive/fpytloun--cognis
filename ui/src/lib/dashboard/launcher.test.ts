import { describe, expect, it, vi } from 'vitest';
import { getDashboardLauncher, registerDashboardLauncher, type DashboardLaunchInput } from './launcher';

const input: DashboardLaunchInput = {
  kind: 'artifact', id: 'art_exact_revision', title: 'Report',
  project_id: null, href: '/library/artifact/art_exact_revision',
};

describe('dashboard launcher lifecycle', () => {
  it('preserves typed input and scope, then rejects retained handles after cleanup', async () => {
    const open = vi.fn().mockResolvedValue(undefined);
    const stop = registerDashboardLauncher({ projectId: null, open });
    const launcher = getDashboardLauncher()!;
    expect(launcher.projectId).toBeNull();
    await launcher.open(input);
    expect(open).toHaveBeenCalledWith(input);
    stop();
    expect(getDashboardLauncher()).toBeNull();
    await expect(launcher.open(input)).rejects.toThrow('no longer active');
    expect(open).toHaveBeenCalledTimes(1);
  });

  it('does not let obsolete cleanup clear a newer mounted scope', async () => {
    const oldOpen = vi.fn();
    const stopOld = registerDashboardLauncher({ projectId: null, open: oldOpen });
    const old = getDashboardLauncher()!;
    const stopNew = registerDashboardLauncher({ projectId: 'project-active', open: vi.fn() });
    stopOld();
    expect(getDashboardLauncher()?.projectId).toBe('project-active');
    await expect(old.open(input)).rejects.toThrow('no longer active');
    expect(oldOpen).not.toHaveBeenCalled();
    stopNew();
    expect(getDashboardLauncher()).toBeNull();
  });
});
