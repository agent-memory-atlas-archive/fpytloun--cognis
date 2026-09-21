export function heroBadges(value: unknown): { label: string; tone: string }[] {
  if (!Array.isArray(value)) return [];
  const tones = new Set(['neutral', 'info', 'success', 'positive', 'warning', 'danger', 'critical']);
  return value.flatMap((item) => {
    if (typeof item === 'string' && item.trim()) return [{ label: item, tone: 'neutral' }];
    if (!item || typeof item !== 'object' || typeof item.label !== 'string' || !item.label.trim()) return [];
    return [{ label: item.label, tone: tones.has(item.tone) ? item.tone : 'neutral' }];
  });
}
