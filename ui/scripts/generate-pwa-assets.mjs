#!/usr/bin/env node
// Keep the existing npm entry point, with one owner for all generated artwork.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('../../scripts/generate_brand_assets.py', import.meta.url));
const result = spawnSync('uv', ['run', script], { stdio: 'inherit' });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
