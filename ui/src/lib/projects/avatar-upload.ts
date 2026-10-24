/** Decode SVG only as an inert browser image; the server receives PNG pixels. */
export async function prepareProjectAvatar(file: File): Promise<File> {
  if (file.type !== 'image/svg+xml' && !file.name.toLowerCase().endsWith('.svg')) return file;
  if (!file.size || file.size > 2 * 1024 * 1024) throw new Error('SVG avatar must be at most 2 MB');
  const url = URL.createObjectURL(new Blob([file], { type: 'image/svg+xml' }));
  try {
    const image = new Image();
    image.src = url;
    await image.decode().catch(() => { throw new Error('Invalid SVG avatar'); });
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 256;
    const context = canvas.getContext('2d');
    if (!context || !image.naturalWidth || !image.naturalHeight) throw new Error('Invalid SVG avatar dimensions');
    const scale = 256 / Math.max(image.naturalWidth, image.naturalHeight);
    const width = image.naturalWidth * scale;
    const height = image.naturalHeight * scale;
    context.drawImage(image, (256 - width) / 2, (256 - height) / 2, width, height);
    const png = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error('Could not convert SVG avatar')), 'image/png'
    ));
    return new File([png], file.name.replace(/\.svg$/i, '') + '.png', { type: 'image/png' });
  } finally {
    URL.revokeObjectURL(url);
  }
}
