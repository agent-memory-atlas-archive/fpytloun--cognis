import type { ProviderMonitor } from '$lib/types/api';

/** Fill short usage cards with health-only providers, then stack the remainder. */
export function providerCards(providers: ProviderMonitor[]): ProviderMonitor[][] {
  const usage: ProviderMonitor[][] = [];
  const shortCards: ProviderMonitor[][] = [];
  const health: ProviderMonitor[] = [];
  for (const provider of providers) {
    const report = provider.usage;
    const bars = report?.ok ? [
      report.primary, report.secondary,
      ...report.additional_rate_limits.flatMap((limit) => [limit.primary, limit.secondary])
    ].filter(Boolean).length : 0;
    if (bars) {
      const card = [provider];
      usage.push(card);
      if (bars <= 2) shortCards.push(card);
    } else health.push(provider);
  }
  let index = 0;
  for (const card of shortCards) {
    if (index < health.length) card.push(health[index++]);
  }
  for (; index < health.length; index += 4) {
    usage.push(health.slice(index, index + 4));
  }
  return usage;
}
