# Viewer font provenance

- Archivo: `@fontsource-variable/archivo@5.3.0`, npm SHA-1
  `23048b3182b66023f52a36761795f79e13c6e284`.
- JetBrains Mono: `@fontsource-variable/jetbrains-mono@5.3.0`, npm SHA-1
  `5738dedd3af40606b0d9b7626f4ba7c4586cb39b`.

Both are SIL Open Font License 1.1. The adjacent OFL files retain the upstream
copyright and license. These are the families used by the approved reference.
No font is fetched at runtime from a third party.

The upstream Latin WOFF2 files were subset with FontTools/Brotli to
`U+0000-00FF,U+2000-206F,U+20AC,U+2122,U+2190-2199`.
Archivo retains weights 400–600. JetBrains Mono is instanced at weight 500.
Other scripts use the declared system fallbacks. Archivo preserves layout
features. Mono retains kerning but omits programming ligatures and hinting.
These controller-package copies match `ui/src/lib/components/rich/fonts/`.
Update both copies together when updating the publication fonts. PDF rendering
loads only the two exact `cognis-asset:` names through the restricted fetcher;
it never reads an authored file path or fetches a remote font.
