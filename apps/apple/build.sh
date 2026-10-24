#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != Darwin ]]; then
  printf '%s\n' "Compile the .app on macOS; build web here with COGNIS_APPLE_BUNDLE=1 npx vite build." >&2
  exit 1
fi
python3 apps/apple/sign_bundle.py --check-config
if [[ "${COGNIS_WEB_PREBUILT:-0}" != 1 ]]; then
  (cd ui && npm ci && COGNIS_APPLE_BUNDLE=1 npx svelte-kit sync && COGNIS_APPLE_BUNDLE=1 npx vite build)
  python3 apps/apple/package_info.py stamp-web
fi
python3 apps/apple/package_info.py check-web
test -f ui/build-apple/index.html
if ! /usr/bin/grep -q 'cognisbundle://app' ui/build-apple/index.html; then
  printf '%s\n' "Missing native asset origin; rebuild with COGNIS_APPLE_BUNDLE=1." >&2
  exit 1
fi
swift build --package-path apps/apple -c release --force-resolved-versions
if [[ "${COGNIS_BRAND_PREBUILT:-0}" != 1 ]]; then
  # SIP strips inherited DYLD_* on entry to system binaries, including env.
  # Pass the value as an env argument so it is assigned after that boundary.
  ICON_ENV=()
  if command -v brew >/dev/null; then
    ICON_ENV+=("DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix cairo)/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}")
  fi
  # Keep script dependencies isolated from an executor's inherited site-packages.
  env -u PYTHONPATH -u PYTHONHOME "${ICON_ENV[@]}" uv run --no-project --python "${COGNIS_ICON_PYTHON:-3.12}" \
    apps/apple/generate_icons.py apps/apple/.build/Brand
fi
iconutil -c icns apps/apple/.build/Brand/Cognis.iconset -o apps/apple/.build/Brand/Cognis.icns
BIN="$(swift build --package-path apps/apple -c release --show-bin-path)"
APP="$ROOT/apps/apple/.build/$(python3 apps/apple/package_info.py app-name)"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/Web"
mkdir -p "$APP/Contents/Frameworks"
FRAMEWORK="$ROOT/apps/apple/.build/artifacts/sparkle/Sparkle/Sparkle.xcframework/macos-arm64_x86_64/Sparkle.framework"
test -d "$FRAMEWORK"
# Keep the complete upstream framework, including signed helpers, symlinks and license.
rsync -a --delete "$FRAMEWORK/" "$APP/Contents/Frameworks/Sparkle.framework/"
mkdir -p "$APP/Contents/Resources/Licenses"
cp "$ROOT/apps/apple/.build/artifacts/sparkle/Sparkle/LICENSE" "$APP/Contents/Resources/Licenses/Sparkle.txt"
cp "$BIN/CognisCompanion" "$APP/Contents/MacOS/Cognis"
# Delete stale resources only within this generated bundle.
rsync -a --delete ui/build-apple/ "$APP/Contents/Resources/Web/"
python3 apps/apple/verify_web.py "$APP/Contents/Resources/Web" "$APP/Contents/Resources/WebAssets.json"
cp apps/apple/.build/Brand/Cognis.icns apps/apple/.build/Brand/CognisMenuTemplate* "$APP/Contents/Resources/"
python3 apps/apple/package_info.py plist --output "$APP/Contents/Info.plist"
python3 apps/apple/verify_package.py "$APP" --mach-o
python3 apps/apple/sign_bundle.py "$APP"
printf '%s\n' "$APP"
