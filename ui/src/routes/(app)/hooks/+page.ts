import { redirect } from '@sveltejs/kit';

// Preserve bookmarks and links from the originally shipped standalone registry.
export function load() {
  redirect(307, '/tools?tab=hooks');
}
