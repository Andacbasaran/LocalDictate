"""Cross-platform login autostart management (Windows Registry, macOS LaunchAgent, Linux XDG)."""

from __future__ import annotations

import logging
import os
import plistlib
import shlex
import sys
from pathlib import Path
from typing import Optional

from . import __bundle_id__

logger = logging.getLogger(__name__)

APP_REG_NAME = "LocalDictate"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
MACOS_PLIST_NAME = f"{__bundle_id__}.plist"
LINUX_DESKTOP_NAME = "localdictate.desktop"


def build_launch_args() -> list[str]:
    """Return argv list to launch LocalDictate at user login."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--minimized"]

    exe = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = exe.with_name("pythonw.exe")
        launcher = pythonw if pythonw.exists() else exe
    else:
        launcher = exe

    project_root = Path(__file__).resolve().parents[2]
    entry = project_root / "main.py"
    if not entry.exists():
        entry = project_root / "run.py"
    return [str(launcher), str(entry), "--minimized"]


def _build_launch_command() -> str:
    """Return a shell-quoted launch command string (Windows Registry / Linux Exec)."""
    args = build_launch_args()
    if sys.platform == "win32":
        return " ".join(f'"{a}"' for a in args)
    return " ".join(shlex.quote(a) for a in args)


def get_macos_plist_path(base_dir: Optional[Path] = None) -> Path:
    agents_dir = base_dir or (Path.home() / "Library" / "LaunchAgents")
    return agents_dir / MACOS_PLIST_NAME


def get_linux_desktop_path(base_dir: Optional[Path] = None) -> Path:
    if base_dir is not None:
        return base_dir / LINUX_DESKTOP_NAME
    xdg_cfg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return xdg_cfg / "autostart" / LINUX_DESKTOP_NAME


def is_autostart_enabled(
    platform_name: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> bool:
    plat = (platform_name or sys.platform).lower()

    if plat == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, APP_REG_NAME)
                return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    if plat == "darwin":
        return get_macos_plist_path(base_dir).exists()

    return get_linux_desktop_path(base_dir).exists()


def set_autostart(
    enabled: bool,
    platform_name: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> bool:
    """Enable or disable launching LocalDictate at OS login."""
    plat = (platform_name or sys.platform).lower()

    if plat == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, _build_launch_command())
                else:
                    try:
                        winreg.DeleteValue(key, APP_REG_NAME)
                    except FileNotFoundError:
                        pass
            return True
        except Exception:
            logger.exception("Failed to update Windows startup registry entry")
            return False

    if plat == "darwin":
        plist_path = get_macos_plist_path(base_dir)
        try:
            if enabled:
                plist_path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "Label": __bundle_id__,
                    "ProgramArguments": build_launch_args(),
                    "RunAtLoad": True,
                    "KeepAlive": False,
                    "ProcessType": "Interactive",
                }
                with plist_path.open("wb") as f:
                    plistlib.dump(payload, f)
            else:
                if plist_path.exists():
                    plist_path.unlink()
            return True
        except Exception:
            logger.exception("Failed to update macOS LaunchAgent plist")
            return False

    # Linux / BSD XDG Autostart
    desktop_path = get_linux_desktop_path(base_dir)
    try:
        if enabled:
            desktop_path.parent.mkdir(parents=True, exist_ok=True)
            exec_cmd = _build_launch_command()
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Version=1.0\n"
                "Name=LocalDictate\n"
                "Comment=100% Offline Desktop AI Speech-to-Text Dictation\n"
                f"Exec={exec_cmd}\n"
                "Icon=localdictate\n"
                "Terminal=false\n"
                "Categories=AudioVideo;Utility;\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            desktop_path.write_text(content, encoding="utf-8")
        else:
            if desktop_path.exists():
                desktop_path.unlink()
        return True
    except Exception:
        logger.exception("Failed to update Linux XDG autostart entry")
        return False
