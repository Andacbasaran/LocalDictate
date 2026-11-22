"""Windows startup (HKCU Run registry key) management."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_REG_NAME = "LocalDictate"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _build_launch_command() -> str:
    """Return the command string to launch LocalDictate at Windows login."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    # Prefer pythonw.exe to avoid a console window flashing on startup
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    launcher = pythonw if pythonw.exists() else exe
    project_root = Path(__file__).resolve().parents[2]
    run_py = project_root / "run.py"
    return f'"{launcher}" "{run_py}"'


def is_autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_REG_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart(enabled: bool) -> bool:
    """Enable or disable launching LocalDictate at Windows login."""
    if os.name != "nt":
        return False
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
