import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import sharp from 'sharp';

const root = resolve(import.meta.dirname, '../..');
const app = readFileSync(resolve(root, 'src/app.html'), 'utf8');
const worker = readFileSync(resolve(root, 'src/service-worker.ts'), 'utf8');

describe('brand resource contracts', () => {
  it('generates opaque maskable icons and a white-on-transparent badge', async () => {
    const { data: badge } = await sharp(resolve(root, 'static/pwa/badge-96.png'))
      .ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    let visible = 0;
    let transparent = 0;
    for (let i = 0; i < badge.length; i += 4) {
      if (badge[i + 3] === 0) transparent++;
      else {
        visible++;
        expect([...badge.subarray(i, i + 3)]).toEqual([255, 255, 255]);
      }
    }
    expect(visible).toBeGreaterThan(0);
    expect(transparent).toBeGreaterThan(visible);
    const { data: mask } = await sharp(resolve(root, 'static/pwa/icon-maskable-512.png'))
      .ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    let minAlpha = 255;
    let maxRadius = 0;
    for (let i = 0; i < mask.length; i += 4) {
      minAlpha = Math.min(minAlpha, mask[i + 3]);
      if (mask[i] !== 11 || mask[i + 1] !== 20 || mask[i + 2] !== 32) {
        const pixel = i / 4;
        maxRadius = Math.max(maxRadius, Math.hypot(pixel % 512 - 255.5, Math.floor(pixel / 512) - 255.5));
      }
    }
    expect(minAlpha).toBe(255);
    expect(maxRadius).toBeGreaterThan(0);
    expect(maxRadius).toBeLessThanOrEqual(512 * 0.4);
  });

  it('provides a script-independent canonical loader with reduced-motion support', () => {
    const doc = new DOMParser().parseFromString(app, 'text/html');
    const loader = doc.querySelector('#cognis-startup-loading')!;
    expect(loader.getAttribute('role')).toBe('status');
    expect(loader.querySelector('img')?.getAttribute('src')).toBe('/brand/cognis-mark-color.svg');
    expect(app).toContain('prefers-reduced-motion: reduce');
    expect(app).toContain("document.getElementById('cognis-startup-loading')?.remove()");
    expect(doc.querySelector('[rel="mask-icon"]')?.getAttribute('href')).toBe('/brand/cognis-mark.svg');
  });

  it('ships and precaches every runtime brand resource without remote fetches', () => {
    const precache = worker.match(/const PRECACHE_STATIC_FILES = new Set\(\[([\s\S]*?)\]\)/)![1];
    for (const resource of [
      '/brand/cognis-mark.svg', '/brand/cognis-mark-color.svg',
      '/pwa/badge-96.png', '/pwa/icon-192.png', '/favicon.svg', '/favicon.ico'
    ]) {
      expect(precache).toContain(`'${resource}'`);
      expect(existsSync(resolve(root, `static${resource}`))).toBe(true);
    }
    expect(worker.match(/badge: '\/pwa\/badge-96.png'/g)).toHaveLength(2);
    const notifications = readFileSync(resolve(root, 'src/lib/notifications.ts'), 'utf8');
    expect(notifications).toContain("icon: '/pwa/icon-192.png'");
    expect(notifications).not.toContain('/favicon.png');
  });

  it('keeps manifest and Apple splash references backed by generated files', () => {
    const manifest = JSON.parse(readFileSync(resolve(root, 'static/manifest.webmanifest'), 'utf8'));
    for (const icon of manifest.icons) expect(existsSync(resolve(root, `static${icon.src}`))).toBe(true);
    const doc = new DOMParser().parseFromString(app, 'text/html');
    for (const link of doc.querySelectorAll('[rel="apple-touch-startup-image"]')) {
      expect(existsSync(resolve(root, `static${link.getAttribute('href')}`))).toBe(true);
    }
  });
});
