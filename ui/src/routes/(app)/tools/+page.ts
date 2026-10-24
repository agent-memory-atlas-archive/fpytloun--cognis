import type { PageLoad } from './$types';

export const load: PageLoad = ({ url }) => ({
  tab: url.searchParams.get('tab') ?? 'builtin'
});
