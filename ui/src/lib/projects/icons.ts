import Briefcase from 'lucide-svelte/icons/briefcase';
import Suitcase from 'lucide-svelte/icons/luggage';
import House from 'lucide-svelte/icons/house';
import Code from 'lucide-svelte/icons/code';
import Heart from 'lucide-svelte/icons/heart';
import Book from 'lucide-svelte/icons/book-open';
import Lightbulb from 'lucide-svelte/icons/lightbulb';
import Plane from 'lucide-svelte/icons/plane';
import Wrench from 'lucide-svelte/icons/wrench';
import GraduationCap from 'lucide-svelte/icons/graduation-cap';
import Mountain from 'lucide-svelte/icons/mountain';
import Palette from 'lucide-svelte/icons/palette';
import CognisProjectIcon from '$lib/components/projects/CognisProjectIcon.svelte';

export const projectIcons = [
  { id: 'cognis', label: 'Cognis', component: CognisProjectIcon },
  { id: 'suitcase', label: 'Travel', component: Suitcase },
  { id: 'house', label: 'Home', component: House },
  { id: 'briefcase', label: 'Work', component: Briefcase },
  { id: 'code', label: 'Code', component: Code },
  { id: 'heart', label: 'Health', component: Heart },
  { id: 'book', label: 'Reading', component: Book },
  { id: 'lightbulb', label: 'Ideas', component: Lightbulb },
  { id: 'plane', label: 'Flights', component: Plane },
  { id: 'wrench', label: 'Build', component: Wrench },
  { id: 'graduation', label: 'Learning', component: GraduationCap },
  { id: 'mountain', label: 'Outdoors', component: Mountain },
  { id: 'palette', label: 'Design', component: Palette },
] as const;

export function projectIcon(id: unknown) {
  return projectIcons.find((item) => item.id === id)?.component;
}

export function safeProjectColor(value: unknown): string {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value : '#38bdf8';
}

/** Choose the higher WCAG contrast against the actual project background. */
export function projectIconForeground(color: string): string {
  function luminance(hex: string): number {
    const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255)
      .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  }
  const background = luminance(safeProjectColor(color));
  const dark = luminance('#0f172a');
  return 1.05 / (background + 0.05) >= (Math.max(background, dark) + 0.05) / (Math.min(background, dark) + 0.05)
    ? '#ffffff' : '#0f172a';
}
