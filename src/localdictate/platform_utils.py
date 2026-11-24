"""Cross-platform OS utilities: active window detection, permissions, overlay flags, and routing."""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Terminal app substrings used for Ctrl+Shift+V routing on Linux and code mode routing
TERMINAL_APP_KEYWORDS: Tuple[str, ...] = (
    "terminal",
    "iterm",
    "warp",
    "alacritty",
    "kitty",
    "wezterm",
    "konsole",
    "gnome-terminal",
    "xfce4-terminal",
    "xterm",
    "foot",
    "tilix",
    "hyper",
    "powershell",
    "pwsh",
    "cmd",
    "windowsterminal",
    "wt",
)

# Default App-Aware Auto-Mode Routing table (keyword -> dictation mode)
APP_MODE_ROUTING_DEFAULTS: Dict[str, str] = {
    # Code / IDEs / Terminals
    "code": "code",
    "visual studio code": "code",
    "cursor": "code",
    "windsurf": "code",
    "pycharm": "code",
    "intellij": "code",
    "webstorm": "code",
    "goland": "code",
    "clion": "code",
    "zed": "code",
    "xcode": "code",
    "android studio": "code",
    "sublime": "code",
    "neovim": "code",
    "terminal": "code",
    "iterm": "code",
    "warp": "code",
    "alacritty": "code",
    "kitty": "code",
    "wezterm": "code",
    "powershell": "code",
    "windowsterminal": "code",
    "konsole": "code",
    "gnome-terminal": "code",
    # Email & Formal Docs
    "mail": "formal",
    "outlook": "formal",
    "thunderbird": "formal",
    "spark": "formal",
    "superhuman": "formal",
    "gmail": "formal",
    "winword": "formal",
    "microsoft word": "formal",
    "pages": "formal",
    "libreoffice": "formal",
    # Chat & Messaging
    "slack": "concise",
    "discord": "concise",
    "messages": "concise",
    "whatsapp": "concise",
    "telegram": "concise",
    "teams": "concise",
    "signal": "concise",
    "zoom": "concise",
    # Knowledge / Notes
    "notion": "bullet_notes",
    "obsidian": "bullet_notes",
    "notes": "bullet_notes",
    "bear": "bullet_notes",
    "logseq": "bullet_notes",
    "craft": "bullet_notes",
    "onenote": "bullet_notes",
    "evernote": "bullet_notes",
}


def get_platform_id(platform_name: Optional[str] = None) -> str:
    """Return normalized platform identifier: 'windows', 'macos', or 'linux'."""
    plat = (platform_name or sys.platform).lower()
    if plat == "win32":
        return "windows"
    if plat == "darwin":
        return "macos"
    return "linux"


def get_default_hotkeys(platform_name: Optional[str] = None) -> Tuple[str, str]:
    """Return OS-aware default (toggle_hotkey, ptt_hotkey).

    MacBooks have no Right Control key, so macOS defaults to Option+Space & Right Option.
    """
    plat = (platform_name or sys.platform).lower()
    if plat == "darwin":
        return ("alt+space", "alt_r")
    return ("ctrl+alt+space", "ctrl_r")


def is_wayland() -> bool:
    """Return True if running under a Linux Wayland display session."""
    if not sys.platform.startswith("linux"):
        return False
    return bool(
        os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("XDG_SESSION_TYPE", "").strip().lower() == "wayland"
    )


def check_accessibility_permission() -> bool:
    """Check OS accessibility permission required for global hotkeys and auto-paste.

    On macOS queries ApplicationServices AXIsProcessTrusted().
    On Windows and Linux returns True (no macOS TCC gate).
    """
    if sys.platform != "darwin":
        return True
    try:
        import ctypes.util

        app_svc_path = ctypes.util.find_library("ApplicationServices")
        if not app_svc_path:
            app_svc_path = (
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
            )
        lib = ctypes.cdll.LoadLibrary(app_svc_path)
        lib.AXIsProcessTrusted.argtypes = []
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:
        logger.debug("AXIsProcessTrusted probe failed", exc_info=True)
        return False


def is_terminal_app(app_name: str) -> bool:
    """Return True if the active application name matches a known terminal emulator."""
    low = (app_name or "").strip().lower()
    if not low:
        return False
    return any(kw in low for kw in TERMINAL_APP_KEYWORDS)


def infer_mode_for_app(
    app_name: str,
    custom_rules: Optional[Dict[str, str]] = None,
    default_mode: str = "cleanup",
) -> str:
    """Infer the best dictation style mode for a given foreground application name."""
    low = (app_name or "").strip().lower()
    if not low:
        return default_mode

    # User-defined rules take highest priority (longest key match first)
    if custom_rules:
        for key, mode in sorted(custom_rules.items(), key=lambda kv: len(kv[0]), reverse=True):
            k_low = key.strip().lower()
            if k_low and k_low in low:
                return mode

    for key, mode in sorted(
        APP_MODE_ROUTING_DEFAULTS.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if key in low:
            return mode

    return default_mode


def _get_active_app_windows() -> str:
    """Return foreground process executable stem on Windows using 64-bit-safe ctypes."""
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND

        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE

        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""

        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""

        process_query_limited_info = 0x1000
        handle = kernel32.OpenProcess(process_query_limited_info, False, pid.value)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return Path(buf.value).stem
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        logger.debug("Windows foreground app detection failed", exc_info=True)
    return ""


def _get_active_app_macos() -> str:
    """Return frontmost macOS application name via AppKit/NSWorkspace or osascript fallback."""
    # Fast path via Objective-C runtime (NSWorkspace.sharedWorkspace.frontmostApplication.localizedName)
    try:
        import ctypes.util

        objc_path = ctypes.util.find_library("objc")
        appkit_path = ctypes.util.find_library("AppKit")
        if objc_path and appkit_path:
            ctypes.cdll.LoadLibrary(appkit_path)
            objc = ctypes.cdll.LoadLibrary(objc_path)
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            objc.objc_getClass.restype = ctypes.c_void_p
            objc.sel_registerName.argtypes = [ctypes.c_char_p]
            objc.sel_registerName.restype = ctypes.c_void_p

            msg_id = ctypes.cast(
                objc.objc_msgSend,
                ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
            )
            msg_cstr = ctypes.cast(
                objc.objc_msgSend,
                ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p),
            )

            ns_ws_cls = objc.objc_getClass(b"NSWorkspace")
            if ns_ws_cls:
                shared = msg_id(ns_ws_cls, objc.sel_registerName(b"sharedWorkspace"))
                front = (
                    msg_id(shared, objc.sel_registerName(b"frontmostApplication"))
                    if shared
                    else None
                )
                loc_name = (
                    msg_id(front, objc.sel_registerName(b"localizedName")) if front else None
                )
                if loc_name:
                    raw = msg_cstr(loc_name, objc.sel_registerName(b"UTF8String"))
                    if raw:
                        return raw.decode("utf-8", errors="replace").strip()
    except Exception:
        pass

    # Reliable fallback via osascript
    try:
        res = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
            timeout=0.45,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def _get_active_app_linux() -> str:
    """Return active window class/name on Linux X11 using xdotool or xprop."""
    xdotool = shutil.which("xdotool")
    if xdotool:
        try:
            res = subprocess.run(
                [xdotool, "getactivewindow", "getwindowclassname"],
                capture_output=True,
                text=True,
                timeout=0.35,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass

    xprop = shutil.which("xprop")
    if xprop:
        try:
            root_res = subprocess.run(
                [xprop, "-root", "_NET_ACTIVE_WINDOW"],
                capture_output=True,
                text=True,
                timeout=0.35,
                check=False,
            )
            if root_res.returncode == 0 and "0x" in root_res.stdout:
                win_id = root_res.stdout.strip().split()[-1]
                if win_id and win_id != "0x0":
                    cls_res = subprocess.run(
                        [xprop, "-id", win_id, "WM_CLASS"],
                        capture_output=True,
                        text=True,
                        timeout=0.35,
                        check=False,
                    )
                    if cls_res.returncode == 0 and '"' in cls_res.stdout:
                        parts = [p for p in cls_res.stdout.split('"') if p.strip() and p.strip() != ","]
                        if parts:
                            return parts[-1].strip()
        except Exception:
            pass
    return ""


def get_active_app_name() -> str:
    """Detect the currently focused application name across Windows, macOS, and Linux."""
    if sys.platform == "win32":
        return _get_active_app_windows()
    if sys.platform == "darwin":
        return _get_active_app_macos()
    if sys.platform.startswith("linux"):
        return _get_active_app_linux()
    return ""


def configure_macos_overlay_window(widget) -> bool:
    """Configure Cocoa NSWindow flags so the HUD stays visible across Spaces and never steals focus."""
    if sys.platform != "darwin":
        return False
    try:
        from PyQt6.QtGui import QGuiApplication

        if QGuiApplication.platformName() != "cocoa":
            return False
        import ctypes.util

        objc_path = ctypes.util.find_library("objc")
        if not objc_path:
            return False
        objc = ctypes.cdll.LoadLibrary(objc_path)
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p

        msg_id = ctypes.cast(
            objc.objc_msgSend,
            ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
        )
        msg_void_bool = ctypes.cast(
            objc.objc_msgSend,
            ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool),
        )
        msg_void_long = ctypes.cast(
            objc.objc_msgSend,
            ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long),
        )
        msg_void_ulong = ctypes.cast(
            objc.objc_msgSend,
            ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong),
        )

        ns_view = int(widget.winId())
        if not ns_view:
            return False
        ns_win = msg_id(ns_view, objc.sel_registerName(b"window"))
        if not ns_win:
            return False

        msg_void_bool(ns_win, objc.sel_registerName(b"setHidesOnDeactivate:"), False)
        msg_void_bool(ns_win, objc.sel_registerName(b"setIgnoresMouseEvents:"), True)
        msg_void_bool(ns_win, objc.sel_registerName(b"setHasShadow:"), False)
        # NSStatusWindowLevel (25) keeps pill floating above normal & full-screen apps
        msg_void_long(ns_win, objc.sel_registerName(b"setLevel:"), 25)
        # CanJoinAllSpaces (1) | FullScreenAuxiliary (256)
        msg_void_ulong(ns_win, objc.sel_registerName(b"setCollectionBehavior:"), 1 | 256)
        return True
    except Exception:
        logger.debug("macOS Cocoa overlay setup skipped", exc_info=True)
        return False


def apply_win32_overlay_no_activate(hwnd: int) -> bool:
    """Apply WS_EX_NOACTIVATE | WS_EX_TRANSPARENT using 64-bit-safe Win32 ctypes."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        from ctypes import wintypes

        gwl_exstyle = -20
        ws_ex_noactivate = 0x08000000
        ws_ex_transparent = 0x00000020

        user32 = ctypes.windll.user32
        is_64 = ctypes.sizeof(ctypes.c_void_p) == 8
        long_ptr = ctypes.c_ssize_t

        if is_64 and hasattr(user32, "GetWindowLongPtrW"):
            get_fn = user32.GetWindowLongPtrW
            set_fn = user32.SetWindowLongPtrW
        else:
            get_fn = user32.GetWindowLongW
            set_fn = user32.SetWindowLongW

        get_fn.argtypes = [wintypes.HWND, ctypes.c_int]
        get_fn.restype = long_ptr
        set_fn.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
        set_fn.restype = long_ptr

        style = get_fn(hwnd, gwl_exstyle)
        set_fn(hwnd, gwl_exstyle, style | ws_ex_noactivate | ws_ex_transparent)
        return True
    except Exception:
        logger.debug("Win32 overlay no-activate setup failed", exc_info=True)
        return False
