#!/usr/bin/env python3
"""LocalDictate — Linux Portable .tar.gz & AppDir / AppImage Build Tool.

Usage:
    python scripts/build_linux.py --version 1.0.0 --arch x86_64
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import List, Optional

APP_NAME = "LocalDictate"
DESKTOP_ID = "com.andacbasaran.LocalDictate.desktop"
ICON_NAME = "localdictate"
DEFAULT_VERSION = "1.0.0"


def read_project_version(base_dir: Path) -> str:
    pyproject = base_dir / "pyproject.toml"
    if pyproject.exists():
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            return m.group(1).strip()
    return DEFAULT_VERSION


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_onedir_bundle(base_dir: Path) -> Path:
    print(f"[1/4] Building PyInstaller --onedir bundle '{APP_NAME}'...")
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
        "pynput.keyboard._xorg",
        "--hidden-import",
        "pynput.mouse._xorg",
        "--hidden-import",
        "PyQt6.QtNetwork",
        "--hidden-import",
        "scipy.signal",
    ]

    assets_dir = base_dir / "assets"
    if assets_dir.is_dir():
        cmd.extend(["--add-data", f"{assets_dir}:assets"])

    cmd.append(str(base_dir / "main.py"))

    env = os.environ.copy()
    pyi_cache = base_dir / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)
    subprocess.run(cmd, cwd=str(base_dir), env=env, check=True)

    bundle_dir = base_dir / "dist" / APP_NAME
    if not bundle_dir.is_dir():
        raise RuntimeError(f"Expected PyInstaller bundle directory not found: {bundle_dir}")
    return bundle_dir


def create_tarball(base_dir: Path, bundle_dir: Path, version: str, arch: str) -> Path:
    tar_name = f"{APP_NAME}-v{version}-Linux-{arch}.tar.gz"
    tar_path = base_dir / "dist" / tar_name
    if tar_path.exists():
        tar_path.unlink()

    print(f"[2/4] Packaging portable archive: {tar_name} ...")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bundle_dir, arcname=APP_NAME)
    print(f"[OK] Archive ready: {tar_path} ({tar_path.stat().st_size / (1024 * 1024):.1f} MB)")
    return tar_path


def assemble_appdir(base_dir: Path, bundle_dir: Path) -> Path:
    print(f"[3/4] Assembling dist/{APP_NAME}.AppDir ...")
    appdir = base_dir / "dist" / f"{APP_NAME}.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    usr_bin = appdir / "usr" / "bin"
    usr_apps = appdir / "usr" / "share" / "applications"
    usr_icons = appdir / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
    usr_apps.mkdir(parents=True, exist_ok=True)
    usr_icons.mkdir(parents=True, exist_ok=True)

    shutil.copytree(bundle_dir, usr_bin, symlinks=True)

    apprun_src = base_dir / "packaging" / "linux" / "AppRun"
    apprun_dst = appdir / "AppRun"
    shutil.copy2(apprun_src, apprun_dst)
    apprun_dst.chmod(apprun_dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    desktop_src = base_dir / "packaging" / "linux" / DESKTOP_ID
    shutil.copy2(desktop_src, appdir / DESKTOP_ID)
    shutil.copy2(desktop_src, usr_apps / DESKTOP_ID)

    icon_src = base_dir / "assets" / "app_icon.png"
    if icon_src.exists():
        shutil.copy2(icon_src, appdir / f"{ICON_NAME}.png")
        shutil.copy2(icon_src, appdir / ".DirIcon")
        shutil.copy2(icon_src, usr_icons / f"{ICON_NAME}.png")

    print(f"[OK] AppDir assembled: {appdir}")
    return appdir


def build_appimage(base_dir: Path, appdir: Path, version: str, arch: str) -> Optional[Path]:
    tool = shutil.which("appimagetool")
    if not tool:
        print("[INFO] 'appimagetool' not found on PATH; skipping AppImage generation.")
        return None
    out_path = base_dir / "dist" / f"{APP_NAME}-v{version}-Linux-{arch}.AppImage"
    if out_path.exists():
        out_path.unlink()
    env = os.environ.copy()
    env["ARCH"] = arch
    subprocess.run([tool, str(appdir), str(out_path)], cwd=str(base_dir), env=env, check=True)
    return out_path


def write_checksums(base_dir: Path, artifacts: List[Path]) -> Path:
    sums_path = base_dir / "dist" / "SHA256SUMS-Linux.txt"
    lines = [f"{sha256_file(p)}  {p.name}\n" for p in artifacts]
    sums_path.write_text("".join(lines), encoding="ascii")
    return sums_path


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("[ERROR] build_linux.py must be run on Linux.")
        return 1

    base_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build LocalDictate Linux .tar.gz and AppDir")
    parser.add_argument("--version", default=read_project_version(base_dir))
    parser.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64"])
    parser.add_argument("--skip-appimage", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    bundle = build_onedir_bundle(base_dir)
    artifacts = [create_tarball(base_dir, bundle, version, args.arch)]
    appdir = assemble_appdir(base_dir, bundle)
    if not args.skip_appimage:
        appimg = build_appimage(base_dir, appdir, version, args.arch)
        if appimg:
            artifacts.append(appimg)
    write_checksums(base_dir, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
