export interface Release {
  version: string;
  date: string;
  markdown: string;
}

function compareVersions(left: string, right: string): number {
  const a = left.split('.').map(Number);
  const b = right.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return 0;
}

/** Exclusive lower bound, inclusive upper bound, matching the Markdown exporter. */
export function releasesBetween(releases: Release[], since: string, through: string): Release[] {
  if (!releases.some((release) => release.version === through)) return [];
  if (since && !releases.some((release) => release.version === since)) return [];
  return releases.filter((release) =>
    compareVersions(release.version, through) <= 0 &&
    (!since || compareVersions(release.version, since) > 0)
  );
}
