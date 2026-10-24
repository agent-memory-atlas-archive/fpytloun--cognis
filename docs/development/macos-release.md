# macOS companion packaging

The app is built from the same committed source as its bundled web UI. The
canonical version is `ui/package.json`; tag builds also require matching
controller/common/executor versions. Do not invent an app-only release version.
`COGNIS_APP_BUILD` is an explicit positive build number (CI uses its run number).

## Development

On macOS 15+ with Swift 6, Node 22, Python 3.12, uv and Homebrew Cairo:

```sh
COGNIS_PACKAGE_FLAVOR=preview bash apps/apple/build.sh
python3 apps/apple/package_dmg.py "apps/apple/.build/Cognis Preview.app" \
  --architecture arm64 --output apps/apple/.build/dist
```

Development signs the completed app and the pinned Sparkle nested components
inside-out with ad-hoc signatures. It generates no identity or key. These
signatures bind the bundle identifier, Info.plist and resource seal, but do not
establish Developer ID trust, notarization, Gatekeeper acceptance or notification
authorization. Development DMG filenames contain `-development`.

Keep an installed Preview's bundle ID and profiles. Use the guarded
`apps/apple/install_preview.py` only after the exact committed package and
normal HTTPS boot pass review. It preserves a previous-bundle backup and does
not touch preferences, WebKit stores, cookies, drafts or the separate PWA.
Register only that installed Preview through standard LaunchServices. Do not
reset TCC/notification databases. The user must click Enable Notifications;
record actual UN authorization status, raw error domain/code, Settings name and
delivery separately from signature verification.

The installed executable's `--notification-status` mode prints raw settings and
bundle names as JSON without starting a server session, requesting permission,
changing categories, or resetting notification state. It cannot establish the
display name cached by System Settings or prove a later permission request succeeds.

## Production gate

`COGNIS_SIGNING_MODE=release` requires `COGNIS_RELEASE_BUILD=1`, standard flavor,
an available Developer ID Application certificate SHA-1 in
`COGNIS_SIGNING_IDENTITY`, `COGNIS_SIGNING_TEAM`, and
`COGNIS_NOTARY_PROFILE`. `COGNIS_SIGNING_KEYCHAIN` optionally selects an isolated
keychain. Release packaging rejects dirty source and app/web version mismatch.

The workflow `.github/workflows/macos-release.yml` builds arm64 and x86_64.
Manual dispatch produces development artifacts only. Tag builds require the
protected `macos-release` environment and these **configuration names**, not
values in source:

- Secrets: `APPLE_CERTIFICATE_P12` (base64), `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_NOTARY_KEY_P8`.
- Variables: `APPLE_SIGNING_IDENTITY` (certificate SHA-1), `APPLE_TEAM_ID`,
  `APPLE_NOTARY_KEY_ID`, `APPLE_NOTARY_ISSUER_ID`.

An authorized publisher must configure the environment and existing credentials.
Missing inputs fail closed. CI imports into a temporary keychain and removes its
files afterwards; it never creates an Apple signing identity. No PR-triggered
job receives release secrets.

The package tool verifies nested signatures and architecture, notarizes/staples
the app, creates the DMG, signs/notarizes/staples it, assesses Gatekeeper, and
checks the mounted app before recording success. It emits a versioned DMG,
SHA-256 sidecar and `cognis.macos.dmg.v1` manifest. Checksums are of the final
stapled bytes; DMGs are not claimed to be byte-reproducible.

CI attaches both verified architectures only to an already reviewed draft,
without replacement. It does **not** create or publish releases. Publishing a
GitHub release triggers the repository's PyPI and Docker jobs and requires
separate release-wide qualification and authorization.

## Homebrew gate

The app cask and existing executor formula are separate products. App CI stamps
`COGNIS_DISTRIBUTION=homebrew`, so Sparkle does not compete with Homebrew updates.
No publisher feed/key is required for the initial app DMGs.

After signed assets have actually been released:

```sh
python3 packaging/homebrew/generate_cask.py --assets dist \
  --verify-downloads --output /path/to/task-owned-tap-worktree/Casks/cognis.rb
```

The generator requires both local DMGs, matching provenance and actual hashes,
then downloads immutable versioned public URLs and verifies them before writing.
Synthetic fixtures live only in unit tests. Do not commit a cask before this gate,
publish development artifacts as release assets, use `--no-quarantine`, or bypass
Gatekeeper. Use a fresh tap worktree based on its verified upstream; never alter
tap main implicitly. Run cask syntax/style/audit and clean install/upgrade checks
before separately authorized tap publication.

Private origin and curated GitHub history remain separate. Publish no private
ancestry, operational investigation logs, private URLs or credentials. Public
tree projection, release notes/version choice, tags, publication and origin
integration remain publisher-owned decisions.
