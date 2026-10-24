// Test-only full Apple export. Never install this bundle.
import { access, copyFile, mkdir, rm, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { build } from 'vite';

const route = 'src/routes/dashboard-drag-acceptance';
try { await access(route); throw new Error('Refusing to overwrite an existing route'); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
await mkdir(route);
try {
  await copyFile('src/acceptance/window-drag/+page.svelte', `${route}/+page.svelte`);
  for (const args of [['svelte-kit', 'sync'], ['vite', 'build', '--config', 'vite.workspace-acceptance.config.ts']]) {
    const result = spawnSync(`./node_modules/.bin/${args[0]}`, args.slice(1), {
      env: { ...process.env, COGNIS_APPLE_BUNDLE: '1' }, stdio: 'inherit',
    });
    if (result.status !== 0) throw new Error(`Native fixture export failed: ${args.join(' ')}`);
  }
  await build({
    configFile: false,
    resolve: { alias: { '$lib': resolve('src/lib') } },
    build: {
      outDir: 'build-apple', emptyOutDir: false, target: 'es2022', minify: false,
      lib: {
        entry: resolve('src/acceptance/window-drag/services.ts'),
        name: 'WindowDragServices', formats: ['iife'],
        fileName: () => 'window-drag-services.js',
      },
      rollupOptions: { output: { inlineDynamicImports: true } },
    },
  });
  await writeFile('build-apple/WINDOW_DRAG_ACCEPTANCE_ONLY',
    'Test-only full Apple export. Do not install. Services are synthetic.\n');
} finally {
  await rm(route, { recursive: true, force: true });
}
