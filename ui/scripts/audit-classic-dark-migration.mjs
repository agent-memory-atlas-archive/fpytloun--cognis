#!/usr/bin/env node
// Audits the semantic-token migration against the pre-theme source for
// Classic Dark. Pairs original Tailwind palette utilities removed in each diff
// hunk with semantic utilities added in the same hunk (same variant+utility,
// in order) and reports pairs whose Classic Dark color differs.
// Usage: node scripts/audit-classic-dark-migration.mjs [base] [head]
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import postcss from 'postcss';
import { chromium } from '@playwright/test';

const require = createRequire(import.meta.url);
const palette = require('tailwindcss/colors');
const [base = '07a413ce4', head = 'HEAD'] = process.argv.slice(2);

function expandImports(url) {
  const root = postcss.parse(readFileSync(url, 'utf8'));
  root.walkAtRules('import', (rule) => {
    const path = rule.params.match(/^['"]([^'"]+)['"]$/)[1];
    rule.replaceWith(postcss.parse(expandImports(new URL(path, url))).nodes);
  });
  return root.toString();
}

const css = expandImports(new URL('../src/lib/theme/tokens.css', import.meta.url));
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent(`<style>${css}</style>`);
const roles = await page.evaluate(() => {
  const root = document.documentElement;
  root.dataset.themeFamily = 'classic';
  root.dataset.resolvedTheme = 'dark';
  root.classList.add('dark');
  const style = getComputedStyle(root);
  return Object.fromEntries(Array.from(style).filter((name) => /^--(color|text|alpha)-/.test(name))
    .map((name) => [name.slice(2), style.getPropertyValue(name).trim()]));
});
await browser.close();

const hex = (value) => value.match(/[0-9a-f]{2}/gi).map((part) => parseInt(part, 16));
function originalColor(name) {
  if (name === 'white') return [[255, 255, 255], 1];
  if (name === 'black') return [[0, 0, 0], 1];
  const match = name.match(/^([a-z]+)-(\d{2,3})$/);
  const value = match && palette[match[1]]?.[match[2]];
  return typeof value === 'string' ? [hex(value), 1] : null;
}
// Mirrors tailwind.config.ts: text utilities prefer --text-<role>; tinted
// roles multiply by --alpha-<role>.
function semanticColor(name, kind) {
  const channels = (kind === 'text' && /^\d+ \d+ \d+$/.test(roles[`text-${name}`] ?? ''))
    ? roles[`text-${name}`] : roles[`color-${name}`];
  if (!channels || !/^\d+ \d+ \d+$/.test(channels)) return null;
  const alpha = Number(roles[`alpha-${name}`]) || 1;
  return [channels.split(' ').map(Number), alpha];
}

const UTILITY = /^(bg|text|border|border-[trblxy]|ring|ring-offset|divide|outline|from|via|to|fill|stroke|placeholder|decoration|caret)-(.+)$/;
function tokens(line, resolve) {
  const found = [];
  for (const raw of line.split(/[\s'"`{}]+/)) {
    if (!raw) continue;
    const parts = raw.split(':');
    const utility = parts.pop();
    const match = utility.match(UTILITY);
    if (!match) continue;
    const [, kind, rest] = match;
    const [name, alphaText] = rest.split('/');
    const resolved = resolve(name, kind);
    if (!resolved) continue;
    const [rgb, multiplier] = resolved;
    const alpha = multiplier * (alphaText ? Number(alphaText.replace(/[[\]]/g, '')) / (alphaText.includes('.') ? 1 : 100) : 1);
    found.push({ key: `${parts.join(':')}|${kind}`, token: raw, rgb, alpha });
  }
  return found;
}

// Pass WORKTREE as head to audit uncommitted changes.
const range = head === 'WORKTREE' ? [base] : [base, head];
const diff = execFileSync('git', ['diff', '-U0', ...range, '--', 'src', ':(exclude)*.test.ts', ':(exclude)*.spec.ts'],
  { cwd: new URL('..', import.meta.url), maxBuffer: 1 << 28, encoding: 'utf8' });
const findings = [];
let file = '';
let hunk = null;
const flush = () => {
  if (!hunk) return;
  const removed = new Map();
  for (const line of hunk.removed) for (const t of tokens(line, originalColor)) {
    if (!removed.has(t.key)) removed.set(t.key, []);
    removed.get(t.key).push(t);
  }
  const used = new Map();
  for (const { text, line } of hunk.added) {
   const seen = new Map();
   for (const t of tokens(text, semanticColor)) {
    const occurrence = seen.get(t.token) ?? 0;
    seen.set(t.token, occurrence + 1);
    const list = removed.get(t.key);
    const index = used.get(t.key) ?? 0;
    if (!list || index >= list.length) continue;
    used.set(t.key, index + 1);
    const original = list[index];
    const delta = Math.max(...original.rgb.map((c, i) => Math.abs(c - t.rgb[i])));
    const mismatch = delta > 6 || Math.abs(original.alpha - t.alpha) > 0.05;
    if (mismatch || process.env.AUDIT_ALL) {
      findings.push({ file, line, original: original.token, current: t.token, delta, alpha: [original.alpha, t.alpha],
        originalRgb: original.rgb, currentRgb: t.rgb, mismatch, occurrence });
    }
   }
  }
};
for (const line of diff.split('\n')) {
  if (line.startsWith('+++ ')) { flush(); hunk = null; file = line.slice(6); continue; }
  const header = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)/);
  if (header) { flush(); hunk = { removed: [], added: [], next: Number(header[1]) }; continue; }
  if (!hunk) continue;
  if (line.startsWith('-') && !line.startsWith('---')) hunk.removed.push(line.slice(1));
  else if (line.startsWith('+')) hunk.added.push({ text: line.slice(1), line: hunk.next++ });
}
flush();
if (process.env.AUDIT_ALL) {
  console.log(JSON.stringify({ roles, findings }));
  process.exit(0);
}
for (const f of findings) {
  console.log(`${f.file}:${f.line}\t${f.original} -> ${f.current}\tΔ${f.delta}\tα${f.alpha[0]}→${f.alpha[1]}`);
}
console.error(`${findings.length} Classic Dark mismatches`);
