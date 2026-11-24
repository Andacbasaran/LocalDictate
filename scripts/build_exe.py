#!/usr/bin/env python3
"""LocalDictate — Windows x64 PyInstaller (--onedir) & Portable ZIP Build Tool.

Usage:
    python scripts/build_exe.py
    python scripts/build_exe.py --version 1.0.0
    python scripts/build_exe.py --skip-zip
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "LocalDictate"
DEFAULT_VERSION = "1.0.0"

HIDDEN_IMPORTS = [
    "localdictate",
    "localdictate.audio",
    "localdictate.autostart",
    "localdictate.config",
    "localdictate.controller",
    "localdictate.hardware",
    "localdictate.history",
    "localdictate.hotkeys",
    "localdictate.i18n",
    "localdictate.injector",
    "localdictate.main",
    "localdictate.platform_utils",
    "localdictate.postprocess",
    "localdictate.snippets",
    "localdictate.sounds",
    "localdictate.transcriber",
    "localdictate.updater",
    "localdictate.ui.overlay",
    "localdictate.ui.studio_window",
    "localdictate.ui.tray",
    "localdictate.ui.widgets",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "PyQt6.QtNetwork",
    "certifi",
    "faster_whisper",
    "ctranslate2",
    "sounddevice",
    "scipy.signal",
]


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


def build_onedir(base_dir: Path) -> Path:
    print(f"[1/2] Building Windows PyInstaller --onedir bundle '{APP_NAME}'...")
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
    ]
    for mod in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", mod])

    ico_path = base_dir / "assets" / "app_icon.ico"
    if ico_path.exists():
        cmd.extend(["--icon", str(ico_path)])

    assets_dir = base_dir / "assets"
    if assets_dir.is_dir():
        sep = ";" if os.name == "nt" else ":"
        cmd.extend(["--add-data", f"{assets_dir}{sep}assets"])

    cmd.append(str(base_dir / "main.py"))

    env = os.environ.copy()
    pyi_cache = base_dir / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)

    subprocess.run(cmd, cwd=str(base_dir), env=env, check=True)
    bundle_dir = base_dir / "dist" / APP_NAME
    if not bundle_dir.is_dir():
        raise RuntimeError(f"Expected PyInstaller bundle directory not found: {bundle_dir}")
    print(f"[OK] Bundle ready: {bundle_dir}")
    return bundle_dir


def create_portable_zip(base_dir: Path, bundle_dir: Path, version: str) -> Path:
    zip_name = f"{APP_NAME}-Portable-v{version}-Windows-x64.zip"
    zip_path = base_dir / "dist" / zip_name
    if zip_path.exists():
        zip_path.unlink()

    print(f"[2/2] Packaging portable ZIP: {zip_name} ...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in sorted(bundle_dir.rglob("*")):
            if file_path.is_file():
                arcname = Path(APP_NAME) / file_path.relative_to(bundle_dir)
                zf.write(file_path, arcname=str(arcname))

    digest = sha256_file(zip_path)
    sums = base_dir / "dist" / "SHA256SUMS-Windows.txt"
    sums.write_text(f"{digest}  {zip_name}\n", encoding="ascii")
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[OK] Portable ZIP ready: {zip_path} ({size_mb:.1f} MB)")
    print(f"[OK] SHA-256: {digest}")
    return zip_path


def main() -> int:
    base_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build LocalDictate Windows --onedir and Portable ZIP")
    parser.add_argument("--version", default=read_project_version(base_dir))
    parser.add_argument("--skip-zip", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    bundle = build_onedir(base_dir)
    if not args.skip_zip:
        create_portable_zip(base_dir, bundle, version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
