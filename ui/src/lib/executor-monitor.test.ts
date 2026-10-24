import { describe, expect, it } from 'vitest';
import { ageExecutor, appendResourceSample, resourceChartPaths, type ResourceSample } from './executor-monitor';
import type { ExecutorConfig, ExecutorResourceSnapshot } from './types/api';

const snapshot = (seconds: number): ExecutorResourceSnapshot => ({
  schema_version: 1, observed_at: new Date(seconds * 1000).toISOString(),
  freshness: { age_seconds: 2, stale_after_seconds: 120, stale: false },
  os: 'linux', arch: 'x86_64',
  cpu: { utilization_percent: 30, model: null, logical_cores: 8, physical_cores: 4 },
  memory: { used_bytes: 50, total_bytes: 100, available_bytes: 50, unified: false },
  accelerators: null, ollama: null, ollama_model_store: null, runtime: null
});

describe('executor monitor history', () => {
  it('appends only newer measurements and preserves missing GPU data', () => {
    const history = appendResourceSample([], snapshot(100));
    expect(history[0]).toMatchObject({ cpu: 30, memory: 50, gpu: null });
    expect(appendResourceSample(history, snapshot(100))).toBe(history);
    expect(appendResourceSample(history, snapshot(99))).toBe(history);
    expect(appendResourceSample(history, null)).toBe(history);
  });

  it('bounds the window and number of points', () => {
    let history: ResourceSample[] = [];
    for (let time = 0; time < 4000; time += 10) history = appendResourceSample(history, snapshot(time));
    expect(history).toHaveLength(80);
    expect(history.at(-1)!.time - history[0].time).toBeLessThanOrEqual(20 * 60_000);
  });

  it('uses real time spacing and breaks charts across missing data and disconnects', () => {
    const point = (time: number, cpu: number | null): ResourceSample => ({ time, cpu, memory: null, gpu: null });
    const paths = resourceChartPaths([point(0, 25), point(30_000, 50), point(60_000, null), point(90_000, 60), point(300_000, 40)], 'cpu');
    expect(paths).toHaveLength(3);
    expect(paths[0]).toContain(' L');
    expect(resourceChartPaths([], 'gpu')).toEqual([]);
  });

  it('ages receipt freshness locally rather than trusting executor clock skew', () => {
    const executor = { resource_snapshot: snapshot(100) } as ExecutorConfig;
    expect(ageExecutor(executor, 119).resource_snapshot?.freshness).toMatchObject({ stale: true, age_seconds: 121 });
    expect(ageExecutor(executor, -10).resource_snapshot?.freshness?.age_seconds).toBe(2);
    expect(executor.resource_snapshot?.freshness?.age_seconds).toBe(2);
  });
});
