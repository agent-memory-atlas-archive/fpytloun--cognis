import type { ModelEntry } from '$lib/types/api';
import { MODEL_ENTRY_KEYS } from '$lib/providers';

const excluded = new Set<keyof ModelEntry>(['model_id', 'runtime_metadata', 'provider_metadata']);

function canonical(value: unknown): string {
  if (Array.isArray(value)) return JSON.stringify([...value].sort());
  return JSON.stringify(value ?? null);
}

/** Compare only fields the registry actually supplies, not invented defaults. */
export function modelDrift(model: ModelEntry, registry: ModelEntry | null): (keyof ModelEntry)[] {
  if (!registry || registry.model_id !== model.model_id) return [];
  return MODEL_ENTRY_KEYS.filter((key) =>
    !excluded.has(key) && Object.hasOwn(registry, key) && registry[key] !== undefined &&
    canonical(model[key]) !== canonical(registry[key])
  );
}

/** Reset one or all supplied fields. Missing registry fields remain untouched. */
export function resetModelDrift(
  model: ModelEntry, registry: ModelEntry, field?: keyof ModelEntry
): ModelEntry {
  const result = JSON.parse(JSON.stringify(model)) as ModelEntry;
  const fields = modelDrift(model, registry).filter((key) => !field || key === field);
  for (const key of fields) {
    Object.assign(result, { [key]: JSON.parse(JSON.stringify(registry[key])) });
  }
  result._configuredFields = [...new Set([...(result._configuredFields || []), ...fields])];
  return result;
}
