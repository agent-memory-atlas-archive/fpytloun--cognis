# Cognis brand assets

## Authoritative geometry

`ui/static/brand/cognis-mark.svg` is the editable vector master. It redraws the
existing Cognis orbital brain mark as four closed paths and a central focus
point. It is not a new logo concept.

The former `favicon.svg` and `pwa/icon.svg` wrapped a JPEG. Both are now generated
true vectors. Do not reintroduce raster wrappers or remove backgrounds at render time.

The master has no raster image, background rectangle, external reference,
font, filter, script, or embedded data. Its transparent negative space is part
of the mark. Preserve the paths, proportions, orientation, and center point.

## Variants

- **Monochrome and inline:** use the master with `currentColor`. An external
  `<img>` does not inherit text color; use an inline SVG component or a CSS
  mask when the surrounding text should control the color.
- **Menu bar:** render the exact master as an opaque black alpha template.
  Use the platform's template-image tinting, not a hard-coded white or green
  image. Keep the transparent background and preserve aspect ratio.
- **Color:** use the generated jade-gradient variant, including its pale
  center point. Do not introduce a black backdrop, a raster texture, or a
  baked shadow.
- **Application and install icons:** place the mark inside an appropriately
  padded square icon canvas. A deliberate platform icon background is
  acceptable; it must not be part of the reusable mark.

Raster PNG, ICO, ICNS, and Apple iconset outputs are generated distribution
assets, not sources. Platforms that require raster images must continue to
receive them.

## Integration rules

- Reuse the same geometry for web, PWA, desktop, and future Apple targets.
- Inline decorative uses should be hidden from assistive technology. An
  interactive control needs its own accessible name, not a duplicate logo
  announcement.
- Check at 16, 18, 22, 32, and 128 CSS points on light and dark backgrounds.
- Never clear user data or change application behavior to update branding.

## Web consumers and audit

`CognisLogo.svelte` imports the master and generated color variant at build time.
It supports `variant="mono"` (inherited text color), optional `label`, and sizing
classes. Without a label it is decorative. All SVG IDs are scoped per instance;
there is no remote image request or duplicated path source.

Sidebar, collapsed navigation, mobile header, login, and both setup states use
this component. The pre-JavaScript loading screen uses the static color vector,
removed by the existing startup-success hook. Recovery and error screens have
text headings rather than separate brand artwork. Semantic Lucide controls,
memory/thinking icons, user/agent avatars, and test sample images are not branding.
README uses the color vector; architecture diagrams and historical product
screenshots remain explanatory content, not replacement logo sources.

The service worker precaches both static vectors and notification assets.
Inline component geometry is bundled into precached JavaScript. Apple startup
screens retain the existing on-demand caching policy to avoid downloading large,
device-specific images during every installation.

## Generation and retained raster exceptions

Run `uv run scripts/generate_brand_assets.py` from the repository root, or
`npm run generate:pwa-assets` from `ui/` (requires `uv`). The npm entry point
delegates to the same pinned Python generator; it cannot restore the old JPEG.

Generated raster outputs are intentional platform adapters:

- Transparent 192/512 PNGs for installation and browser notifications.
- White-on-transparent 96 PNG for monochrome notification badges.
- Opaque 512 maskable and 180 Apple touch icons for platform composition.
- Device-sized opaque Apple startup PNGs, using the canonical transparent mark.
- Multi-size ICO for browsers that need it.

`Logo.JPG` and `files/banner.jpg`, if present, are historical artwork, not runtime
or generation inputs. Historical screenshots are retained unchanged to avoid
misrepresenting captured product states. Native Mac assets are maintained
separately and are outside the web migration.
