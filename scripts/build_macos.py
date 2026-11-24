#!/usr/bin/env python3
"""LocalDictate — macOS (Apple Silicon arm64 / Intel x86_64) .app & .dmg Release Builder.

Features:
1. Ensures assets/app_icon.icns exists from assets/app_icon.png.
2. Builds standalone 'dist/LocalDictate.app' via PyInstaller (--onedir --windowed).
3. Injects NSMicrophoneUsageDescription, NSAppleEventsUsageDescription, and Retina keys into Info.plist.
4. Signs the bundle (ad-hoc or MACOS_SIGN_IDENTITY Developer ID).
5. Packages a compressed drag-to-Applications .dmg with FIRST_LAUNCH_GUIDE.txt and SHA-256 checksum.

Usage:
    python scripts/build_macos.py --version 1.0.0 --arch arm64
"""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

APP_NAME = "LocalDictate"
BUNDLE_ID = "com.andacbasaran.localdictate"
DEFAULT_VERSION = "1.0.0"

FIRST_LAUNCH_GUIDE = """\
========================================================================
LocalDictate v1.0.0 — macOS Quick Start & Permissions Guide
========================================================================

1. INSTALL
   Drag "LocalDictate.app" into your "Applications" folder.

2. FIRST LAUNCH (Unsigned Open-Source Gatekeeper Notice)
   If macOS says the app cannot be verified, run once in Terminal:
     xattr -cr "/Applications/LocalDictate.app"
   Or open System Settings -> Privacy & Security -> "Open Anyway".

3. REQUIRED PERMISSIONS
   - Microphone: Granted automatically on first dictation.
   - Accessibility (for global Option+Space hotkey & Cmd+V auto-paste):
     System Settings -> Privacy & Security -> Accessibility -> enable LocalDictate.
   - Input Monitoring (macOS Ventura+):
     System Settings -> Privacy & Security -> Input Monitoring -> enable LocalDictate.

4. DEFAULT MACOS HOTKEYS
   - Toggle Dictation : Option + Space
   - Push-to-Talk     : Right Option
   - Cancel Recording : Esc

5. LOCAL DATA LOCATION
   ~/Library/Application Support/LocalDictate
========================================================================
"""


def read_project_version(base_dir: Path) -> str:
    pyproject = base_dir / "pyproject.toml"
    if pyproject.exists():
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            return m.group(1).strip()
    return DEFAULT_VERSION


def ensure_icns_icon(base_dir: Path) -> Optional[Path]:
    assets_dir = base_dir / "assets"
    icns_path = assets_dir / "app_icon.icns"
    png_path = assets_dir / "app_icon.png"

    if icns_path.exists() and icns_path.stat().st_size > 1024:
        return icns_path
    if not png_path.exists():
        print("[WARN] assets/app_icon.png not found; default icon will be used.")
        return None

    print("[1/5] Generating macOS app_icon.icns from assets/app_icon.png...")
    tmp_dir = Path(tempfile.mkdtemp(prefix="localdictate_icns_"))
    try:
        mapping = [
            (b"icp4", 16),
            (b"ic11", 32),
            (b"icp5", 32),
            (b"ic12", 64),
            (b"ic07", 128),
            (b"ic13", 256),
            (b"ic08", 256),
            (b"ic14", 512),
            (b"ic09", 512),
            (b"ic10", 1024),
        ]
        chunks = []
        for ostype, px in mapping:
            out_png = tmp_dir / f"icon_{px}_{ostype.decode('ascii')}.png"
            subprocess.run(
                ["sips", "-s", "format", "png", "-z", str(px), str(px), str(png_path), "--out", str(out_png)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            data = out_png.read_bytes()
            chunks.append(ostype + struct.pack(">I", len(data) + 8) + data)
        body = b"".join(chunks)
        icns_path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
        return icns_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def build_app_bundle(base_dir: Path, icns_path: Optional[Path], arch: str) -> Path:
    print(f"[2/5] Building '{APP_NAME}.app' ({arch}) with PyInstaller...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--osx-bundle-identifier",
        BUNDLE_ID,
        "--target-arch",
        arch,
        "--paths",
        str(base_dir / "src"),
        "--collect-all",
        "faster_whisper",
        "--collect-all",
        "ctranslate2",
        "--collect-all",
        "onnxruntime",
        "--collect-all",
        "av",
        "--collect-all",
        "sounddevice",
        "--collect-data",
        "certifi",
        "--collect-submodules",
        "localdictate",
        "--hidden-import",
        "pynput.keyboard._darwin",
        "--hidden-import",
        "pynput.mouse._darwin",
        "--hidden-import",
        "PyQt6.QtNetwork",
    ]
    if icns_path and icns_path.exists():
        cmd.extend(["--icon", str(icns_path), "--add-data", f"{icns_path}:assets"])

    png_path = base_dir / "assets" / "app_icon.png"
    if png_path.exists():
        cmd.extend(["--add-data", f"{png_path}:assets"])

    cmd.append(str(base_dir / "main.py"))

    env = os.environ.copy()
    pyi_cache = base_dir / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)
    subprocess.run(cmd, cwd=str(base_dir), env=env, check=True)

    app_path = base_dir / "dist" / f"{APP_NAME}.app"
    if not app_path.is_dir():
        raise RuntimeError(f"Expected .app bundle not found: {app_path}")
    return app_path


def update_info_plist(app_path: Path, version: str) -> None:
    print("[3/5] Updating Info.plist permissions and metadata...")
    plist_path = app_path / "Contents" / "Info.plist"
    with plist_path.open("rb") as f:
        plist = plistlib.load(f)

    plist["CFBundleDisplayName"] = APP_NAME
    plist["CFBundleName"] = APP_NAME
    plist["CFBundleIdentifier"] = BUNDLE_ID
    plist["CFBundleShortVersionString"] = version
    plist["CFBundleVersion"] = version
    plist["LSMinimumSystemVersion"] = "12.0"
    plist["LSApplicationCategoryType"] = "public.app-category.productivity"
    plist["NSHighResolutionCapable"] = True
    plist["NSSupportsAutomaticGraphicsSwitching"] = True
    plist["NSMicrophoneUsageDescription"] = (
        "LocalDictate captures your voice locally on your Mac to transcribe speech into text 100% offline."
    )
    plist["NSAppleEventsUsageDescription"] = (
        "LocalDictate detects the active application for App-Aware Mode Routing and pastes dictated text via Cmd+V."
    )

    with plist_path.open("wb") as f:
        plistlib.dump(plist, f)


def codesign_app(app_path: Path) -> None:
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "-").strip() or "-"
    mode_label = "Ad-hoc" if identity == "-" else f"Developer ID ({identity})"
    print(f"[4/5] Signing '{app_path.name}' ({mode_label})...")

    cmd = ["codesign", "--force", "--deep", "--sign", identity]
    if identity != "-":
        cmd.extend(["--options", "runtime", "--timestamp"])
    cmd.append(str(app_path))
    subprocess.run(cmd, check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app_path)], check=True)
    print("[OK] Code signature verified.")


def create_dmg(base_dir: Path, app_path: Path, version: str, arch: str) -> Path:
    dmg_name = f"{APP_NAME}-v{version}-macOS-{arch}.dmg"
    dmg_path = base_dir / "dist" / dmg_name
    if dmg_path.exists():
        dmg_path.unlink()

    print(f"[5/5] Creating DMG package: {dmg_name} ...")
    staging = base_dir / "build" / "dmg_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(app_path, staging / app_path.name, symlinks=True)
        os.symlink("/Applications", staging / "Applications")
        (staging / "FIRST_LAUNCH_GUIDE.txt").write_text(FIRST_LAUNCH_GUIDE, encoding="utf-8")

        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                f"{APP_NAME} v{version}",
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                "-imagekey",
                "zlib-level=9",
                str(dmg_path),
            ],
            check=True,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    sha = hashlib.sha256()
    with dmg_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    digest = sha.hexdigest()
    (base_dir / "dist" / "SHA256SUMS-macOS.txt").write_text(f"{digest}  {dmg_name}\n", encoding="ascii")
    print(f"[OK] DMG ready: {dmg_path} ({dmg_path.stat().st_size / (1024 * 1024):.1f} MB)")
    print(f"[OK] SHA-256:  {digest}")
    return dmg_path


def main() -> int:
    if sys.platform != "darwin":
        print("[ERROR] build_macos.py must be run on macOS.")
        return 1

    base_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build LocalDictate macOS .app and .dmg")
    parser.add_argument("--version", default=read_project_version(base_dir))
    parser.add_argument("--arch", default="arm64", choices=["arm64", "x86_64", "universal2"])
    parser.add_argument("--skip-dmg", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    icns_path = ensure_icns_icon(base_dir)
    app_path = build_app_bundle(base_dir, icns_path, args.arch)
    update_info_plist(app_path, version)
    codesign_app(app_path)
    if not args.skip_dmg:
        create_dmg(base_dir, app_path, version, args.arch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
