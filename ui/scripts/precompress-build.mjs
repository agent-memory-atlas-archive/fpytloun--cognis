#!/usr/bin/env node
// Write .br and .gz sidecars next to compressible build outputs so the Python
// SPA middleware can serve compressed bytes without runtime CPU cost.
import { readdir, readFile, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { brotliCompress, constants, gzip } from 'node:zlib';
import { promisify } from 'node:util';

const brotli = promisify(brotliCompress);
const gz = promisify(gzip);

const COMPRESSIBLE = /\.(?:js|mjs|css|html|json|svg|webmanifest|txt|map|xml|bcmap|wasm)$/i;
const MIN_BYTES = 1024;

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else if (entry.isFile()) yield path;
  }
}

async function compressFile(path) {
  const source = await readFile(path);
  if (source.length < MIN_BYTES) return [0, 0];
  const [br, gzipped] = await Promise.all([
    brotli(source, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: 11,
        [constants.BROTLI_PARAM_SIZE_HINT]: source.length
      }
    }),
    gz(source, { level: 9 })
  ]);
  let written = 0;
  if (br.length < source.length * 0.95) {
    await writeFile(`${path}.br`, br);
    written += 1;
  }
  if (gzipped.length < source.length * 0.95) {
    await writeFile(`${path}.gz`, gzipped);
    written += 1;
  }
  return [source.length, br.length < source.length ? br.length : source.length, written];
}

async function main() {
  const root = process.argv[2] ?? 'build';
  try {
    await stat(root);
  } catch {
    console.error(`precompress: ${root} does not exist`);
    process.exit(1);
  }
  const files = [];
  for await (const path of walk(root)) {
    if (COMPRESSIBLE.test(path)) files.push(path);
  }
  let rawBytes = 0;
  let brBytes = 0;
  let sidecars = 0;
  const concurrency = 8;
  for (let i = 0; i < files.length; i += concurrency) {
    const results = await Promise.all(files.slice(i, i + concurrency).map(compressFile));
    for (const [raw, br, written] of results) {
      rawBytes += raw;
      brBytes += br;
      sidecars += written ?? 0;
    }
  }
  const mb = (value) => (value / 1024 / 1024).toFixed(2);
  console.log(`precompress: ${sidecars} sidecars for ${files.length} files in ${root} (${mb(rawBytes)} MB -> ${mb(brBytes)} MB brotli)`);
}

await main();
