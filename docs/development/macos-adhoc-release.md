# Public ad-hoc Mac distribution

This is an intentional distribution class, not a Developer ID release and not
a development artifact. No version bump, tag, publication, tap change or Apple
credential setup is implied by the tooling.

## Classes and trust

| Mode | Build | Signature | Apple trust / notarization |
| --- | --- | --- | --- |
| `development` | Local, possibly dirty; `-development` DMG | Ad-hoc | None |
| `adhoc` | Clean standard release, matching source/web/version | Ad-hoc, sealed bundle | None |
| `release` | Clean standard release | Developer ID, hardened runtime | Required notarization, stapling and assessment |

`COGNIS_SIGNING_MODE=adhoc` requires `COGNIS_RELEASE_BUILD=1`, standard flavor
and **no** Apple identity, team, keychain or notary profile. The signature binds
Info.plist, resources and nested code. It proves integrity, not publisher trust.
Manifests record `signing: adhoc`, `team: null`, `notarized: false`,
`appleTrusted: false`, plus mounted verification and actual architecture/hash.
The source commit, source digest, build, web version and distribution are retained
in the sealed build identity. DMGs are not byte-reproducible.

## Publisher-owned gates

1. Integrate reviewed UX and tooling slices, then select the next minor canonical
   version. Align UI/controller/common/executor and lockfiles. Do not reuse an old
   project release or attach Mac assets to `v0.17.1`.
2. Complete release-wide qualification, including isolated compatibility E2E
   against the supported public controller. Version equality alone is not proof
   of API compatibility; optional attention actions must degrade safely.
3. Curate the public tree without private history, operational references or
   credentials. Verify projected tree equality and off-hours public metadata.
4. Create a new immutable `macos-v<canonical version>` tag at the reviewed public
   commit. Create its reviewed GitHub draft as a **prerelease** and explicitly
   set `--latest=false`. Mac-only releases must remain prereleases so they cannot
   replace the project release in GitHub's latest channel.
5. Dispatch `.github/workflows/macos-release.yml` with that existing tag and
   explicit `mode: adhoc`. This workflow is dispatch-only: neither project tags
   nor Mac tags implicitly select ad-hoc. Select `mode: release` explicitly for
   the Developer ID path, which fails closed without credentials. Ad-hoc jobs
   receive no Apple secrets.
6. Both architecture jobs inspect signatures, package, mount read-only and
   re-inspect the app. Attachment validates both hashes, matching identities,
   exact tag/source/mode and seals. The protected `macos-attachments` environment
   is the review gate. It accepts only an existing draft prerelease and uploads
   without `--clobber`; retries cannot replace assets. Review both manifests,
   checksum sidecars and workflow logs before separately authorized publication.
7. Publish as a prerelease with `--latest=false`. Python/Docker release jobs
   accept only project `v<SemVer>` tags, not `macos-v` tags. Normal executor asset
   tags remain unchanged.

## Homebrew after publication

From downloaded, published arm64 and x86_64 DMGs and their manifests:

```sh
python3 packaging/homebrew/generate_cask.py --assets dist \
  --release-tag "macos-v${VERSION}" --allow-adhoc --verify-downloads \
  --output /path/to/task-owned-tap-worktree/Casks/cognis.rb
```

`VERSION` must be the frozen canonical version. There is no fabricated cask in
source. The generator checks actual local hashes, matching provenance and
truthful no-team/no-notary metadata, then downloads both exact public Mac-tag
URLs and checks their bytes. Default generation still requires notarized assets.
Only after this gate may the publisher update the real tap in an isolated
worktree. Run `ruby -c`, `brew style`, `brew audit --cask --strict` and clean-device
install/upgrade qualification. Do not install over the active development Preview.
Do not change the executor formula.

## First launch

This app is **not Apple Developer ID signed or notarized**. macOS can block it.
Download only from the reviewed release and compare its SHA-256. Install the app
using the DMG Applications shortcut or the cask, then attempt to open it.
If you trust it, use **System Settings → Privacy & Security → Open Anyway** and
confirm the system prompt. The option may appear only after a blocked launch.
Managed devices may prohibit this override; ask the administrator or wait for
a trusted release. There is no guarantee that ad-hoc apps are permitted on every
macOS policy/version.

Do not use `--no-quarantine`, clear extended attributes, disable Gatekeeper or
modify OS permission databases. Signature verification does not establish
notification permission or delivery; qualify those separately through normal UI.

## Future Developer ID transition

Keep `release` strict: real Developer ID certificate/team, hardened runtime,
notary acceptance, staples and Gatekeeper assessments are all required.
An authorized publisher can later configure existing credentials in the protected
trusted environment; this slice creates no keys or secrets. Use a new canonical
version/Mac tag and new immutable assets, omit `--allow-adhoc`, and verify downloads
again before updating the cask. Never relabel or replace old ad-hoc artifacts.
The original trusted packaging guide is `docs/development/macos-release.md`;
its development-only manual-dispatch description predates this explicit mode.
