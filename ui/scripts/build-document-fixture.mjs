// Headless WK test input only. This is not an app route or production export.
import { build } from 'vite';
import { resolve } from 'node:path';
import { readFile, writeFile } from 'node:fs/promises';
const outDir = resolve(process.argv[2] ?? '/tmp/cognis-document-fixture');
await build({
  configFile: false,
  resolve: { alias: { '$lib': resolve('src/lib') } },
  plugins: [{
    name: 'isolated-document-fixture',
    resolveId(id) {
      if (id === '$app/environment' || id === '$env/dynamic/public') return '\0fixture:' + id;
    },
    load(id) {
      if (id === '\0fixture:$app/environment') return 'export const browser = true;';
      if (id === '\0fixture:$env/dynamic/public') return 'export const env = {};';
    },
  }],
  build: {
    outDir, emptyOutDir: true, target: 'safari17', minify: false,
    lib: { entry: resolve('scripts/document-fixture.ts'), name: 'DocumentFixture', formats: ['iife'], fileName: () => 'fixture.js' },
  },
});
await writeFile(resolve(outDir, 'index.html'),
  '<!doctype html><html><head></head><body><script>' +
  (await readFile(resolve(outDir, 'fixture.js'), 'utf8')).replaceAll('</script', '<\\/script') +
  '</script></body></html>');
