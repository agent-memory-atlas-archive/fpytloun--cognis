import sharp from 'sharp';

const [targetDark, currentDark, targetLight, currentLight, output] = process.argv.slice(2);
if (!output) throw new Error('Usage: node compare-rich-viewer.mjs target-dark current-dark target-light current-light output.png');
const width = 1230;
const height = 1135;
const labelHeight = 38;
const inputs = [targetDark, currentDark, targetLight, currentLight];
const labels = ['Claude target / dark', 'Cognis / dark', 'Claude target / light', 'Cognis / light'];
const layers = [];
for (let index = 0; index < inputs.length; index++) {
  // All panels use the same CSS-pixel scale. Only the 1–2px edge discrepancy
  // in the supplied target images is padded; no panel is stretched.
  const panel = await sharp(inputs[index]).resize(width, height, { fit: 'contain', background: '#e5e7eb' }).png().toBuffer();
  const left = index % 2 * width;
  const top = Math.floor(index / 2) * (height + labelHeight);
  const label = Buffer.from(`<svg width="${width}" height="${labelHeight}"><rect width="100%" height="100%" fill="#111827"/><text x="18" y="25" fill="white" font-family="sans-serif" font-size="17">${labels[index]}</text></svg>`);
  layers.push({ input: label, left, top }, { input: panel, left, top: top + labelHeight });
}
await sharp({ create: { width: width * 2, height: (height + labelHeight) * 2, channels: 3, background: '#e5e7eb' } }).composite(layers).png().toFile(output);
