import { readFile } from 'node:fs/promises';
import path from 'node:path';

const directory = path.resolve('standalone-build/offline');
const manifest = JSON.parse(await readFile(path.join(directory, '.vite/manifest.json'), 'utf8'));
const entry = manifest['src/standalone.ts'];
const styles = entry?.css ?? [manifest['style.css']?.file];
if (!entry?.isEntry || !entry.file || !styles.length || styles.some(style => !style)) {
  throw new Error('Offline publication bundle must include its script and styles');
}
if (Object.values(manifest).filter(item => item.file?.endsWith('.js')).length !== 1) {
  throw new Error('Offline publication bundle must contain exactly one JavaScript file');
}
let bytes = (await readFile(path.join(directory, entry.file))).byteLength;
for (const file of styles) {
  const css = await readFile(path.join(directory, file), 'utf8');
  if ([...css.matchAll(/url\(([^)]+)\)/g)].some(match => !/^['"]?data:/.test(match[1]))) {
    throw new Error('Offline publication CSS must embed every font and asset');
  }
  bytes += Buffer.byteLength(css);
}
if (bytes > 8 * 1024 * 1024) throw new Error('Offline renderer exceeds its 8 MiB asset budget');
console.log(`Offline publication bundle: ${bytes} bytes, all styles/fonts embedded`);
