"""Guarded install of this task's human-preview bundle only; never touches user data."""

from __future__ import annotations

import argparse
import ctypes
import os
import plistlib
import shutil
import sys
import uuid
from pathlib import Path

from verify_package import verify_package

PREVIEW_ID = "cz.fpy.cognis.companion.preview"
PREVIEW_NAME = "Cognis Preview.app"


def preview_identity(app: Path) -> dict:
    if app.is_symlink() or not app.is_dir():
        raise ValueError("Preview bundle must be a real directory, not a symlink")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != PREVIEW_ID or info.get("CognisPackageFlavor") != "preview":
        raise ValueError("Refusing to replace a bundle that is not Cognis Preview")
    if "CognisAcceptanceOrigin" in info or "SUFeedURL" in info or "SUPublicEDKey" in info:
        raise ValueError("Preview must not contain a fixed origin or publisher config")
    return info


def exchange(left: Path, right: Path) -> None:
    """Atomically exchange only the validated app and its same-volume staging copy."""
    if sys.platform != "darwin":
        raise RuntimeError("Atomic app replacement requires macOS")
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    rename = libc.renameatx_np
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # Darwin AT_FDCWD and RENAME_SWAP, from the SDK's stdio.h.
    if rename(-2, os.fsencode(left), -2, os.fsencode(right), 0x00000002) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def install(source: Path, applications: Path, commit: str) -> Path:
    info = preview_identity(source)
    if info.get("CognisSourceCommit") != commit or info.get("CognisBuildIdentity", {}).get("dirty"):
        raise ValueError("Install requires the exact committed, clean preview build")
    verify_package(source, mach_o=sys.platform == "darwin")
    if applications.is_symlink():
        raise ValueError("Applications directory must not be a symlink")
    applications.mkdir(exist_ok=True)
    destination = applications / PREVIEW_NAME
    if destination.exists() or destination.is_symlink():
        preview_identity(destination)
    staging = applications / (".Cognis Preview.install-" + uuid.uuid4().hex + ".app")
    exchanged = False
    try:
        shutil.copytree(source, staging, symlinks=True)
        preview_identity(staging)
        verify_package(staging, mach_o=sys.platform == "darwin")
        # Recheck immediately before replacement; never substitute another app.
        if destination.exists() or destination.is_symlink():
            preview_identity(destination)
            exchange(staging, destination)
            exchanged = True
            # Preserve the old bundle, too. Preferences/WebKit/Keychain are never copied or erased.
            backup = applications / (".Cognis Preview.previous-" + uuid.uuid4().hex + ".app")
            staging.rename(backup)
            print("Previous preview bundle preserved:", backup)
        else:
            staging.rename(destination)
        return destination
    finally:
        # Only our unique staging copy, never an existing destination or user data.
        if not exchanged and staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Install is supported only on macOS")
    print("Installed:", install(args.source, Path.home() / "Applications", args.commit))
