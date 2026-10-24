import { percentUsed } from '$lib/executors';
import type { ExecutorConfig, ExecutorResourceSnapshot } from '$lib/types/api';

export interface ResourceSample {
  time: number;
  cpu: number | null;
  memory: number | null;
  gpu: number | null;
}

export type ResourceMetric = 'cpu' | 'memory' | 'gpu';
export const HISTORY_WINDOW_MS = 20 * 60_000;
const MAX_SAMPLES = 80;

export function resourceSample(snapshot: ExecutorResourceSnapshot): ResourceSample {
  return {
    time: Date.parse(snapshot.observed_at),
    cpu: snapshot.cpu?.utilization_percent ?? null,
    memory: percentUsed(snapshot.memory?.used_bytes, snapshot.memory?.total_bytes),
    gpu: snapshot.accelerators?.[0]?.utilization_percent ?? null
  };
}

/** Session-local, bounded history; never synthesize points or repeat an old sample. */
export function appendResourceSample(
  history: ResourceSample[],
  snapshot: ExecutorResourceSnapshot | null | undefined
): ResourceSample[] {
  if (!snapshot) return history;
  const sample = resourceSample(snapshot);
  if (!Number.isFinite(sample.time) || sample.time <= (history.at(-1)?.time ?? -Infinity)) return history;
  return [...history.filter((point) => point.time >= sample.time - HISTORY_WINDOW_MS), sample].slice(-MAX_SAMPLES);
}

/** Age the server's receipt-time freshness with a local clock, without network reads. */
export function ageExecutor(executor: ExecutorConfig, elapsedSeconds: number): ExecutorConfig {
  const snapshot = executor.resource_snapshot;
  if (!snapshot?.freshness) return executor;
  const age = snapshot.freshness.age_seconds + Math.max(0, elapsedSeconds);
  return {
    ...executor,
    resource_snapshot: {
      ...snapshot,
      freshness: {
        ...snapshot.freshness,
        age_seconds: age,
        stale: age > snapshot.freshness.stale_after_seconds
      }
    }
  };
}

export function resourceChartPaths(history: ResourceSample[], metric: ResourceMetric): string[] {
  const latest = history.at(-1)?.time;
  if (latest === undefined) return [];
  const start = latest - HISTORY_WINDOW_MS;
  const paths: string[] = [];
  let path = '';
  let previousTime: number | null = null;
  for (const sample of history) {
    const value = sample[metric];
    // Missing values and long disconnects must not look like measured continuity.
    if (value === null || (previousTime !== null && sample.time - previousTime > 120_000)) {
      if (path) paths.push(path);
      path = '';
    }
    if (value !== null) {
      const x = Math.max(0, (sample.time - start) / HISTORY_WINDOW_MS * 240);
      const y = 48 - Math.max(0, Math.min(100, value)) / 100 * 44;
      path += `${path ? ' L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
    }
    previousTime = sample.time;
  }
  if (path) paths.push(path);
  return paths;
}
