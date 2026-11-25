"""Cross-platform, clipboard-safe text injection into the currently focused window.

Supports:
- Windows: Win32 SendInput (Ctrl+V) with 64-bit safe ctypes argtypes/restype
- macOS: Quartz CGEventCreateKeyboardEvent (Cmd+V, kVK_ANSI_V = 0x09) + osascript fallback
- Linux: Wayland (wtype / ydotool) and X11 (xdotool / pynput), with Ctrl+Shift+V for terminals

Critical safety guarantee:
  Previous clipboard contents are NEVER restored if the paste command did not actually execute,
  ensuring dictated text remains on the clipboard for manual paste instead of being silently lost.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

import pyperclip

from .platform_utils import check_accessibility_permission, is_terminal_app, is_wayland

logger = logging.getLogger(__name__)

# Win32 SendInput constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_MENU = 0x12
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_V = 0x56

# macOS Quartz key constants
KVK_ANSI_V = 0x09
KCG_EVENT_FLAG_MASK_COMMAND = 0x00100000
KCG_HID_EVENT_TAP = 0


if os.name == "nt":
    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_uint32),
            ("time", ctypes.c_uint32),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("_union",)
        _fields_ = [
            ("type", ctypes.c_uint32),
            ("_union", _INPUT_UNION),
        ]


def _win32_send_key_events(events: list[tuple[int, int]]) -> bool:
    """Send keyboard events via Win32 SendInput with strict 64-bit argtypes/restype."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
        user32.SendInput.restype = ctypes.c_uint

        arr = (INPUT * len(events))()
        for i, (vk, flags) in enumerate(events):
            arr[i].type = INPUT_KEYBOARD
            arr[i].ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
        sent = user32.SendInput(len(events), ctypes.byref(arr), ctypes.sizeof(INPUT))
        return int(sent) == len(events)
    except Exception:
        logger.exception("Win32 SendInput failed")
        return False


def _win32_release_modifiers_if_held() -> None:
    """Release any modifier keys still held from triggering the dictation hotkey."""
    if os.name != "nt":
        return
    try:
        user32 = ctypes.windll.user32
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        release_events: list[tuple[int, int]] = []
        for vk in (VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU, VK_LSHIFT, VK_RSHIFT, 0x5B, 0x5C):
            if user32.GetAsyncKeyState(vk) & 0x8000:
                release_events.append((vk, KEYEVENTF_KEYUP))
        if release_events:
            _win32_send_key_events(release_events)
            time.sleep(0.02)
    except Exception:
        pass


def _paste_windows() -> bool:
    _win32_release_modifiers_if_held()
    return _win32_send_key_events([
        (VK_CONTROL, 0),
        (VK_V, 0),
        (VK_V, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ])


def _paste_macos_quartz() -> bool:
    """Send Cmd+V on macOS via CoreGraphics CGEventCreateKeyboardEvent."""
    if sys.platform != "darwin":
        return False
    if not check_accessibility_permission():
        logger.warning(
            "macOS Accessibility permission not granted; skipping Quartz auto-paste (text kept in clipboard)."
        )
        return False
    try:
        import ctypes.util

        cg_path = ctypes.util.find_library("CoreGraphics")
        if not cg_path:
            cg_path = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        cg = ctypes.cdll.LoadLibrary(cg_path)

        cg.CGEventCreateKeyboardEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_bool,
        ]
        cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p

        cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        cg.CGEventSetFlags.restype = None

        cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cg.CGEventPost.restype = None

        cf_path = ctypes.util.find_library("CoreFoundation") or cg_path
        cf = ctypes.cdll.LoadLibrary(cf_path)
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None

        ev_down = cg.CGEventCreateKeyboardEvent(None, KVK_ANSI_V, True)
        ev_up = cg.CGEventCreateKeyboardEvent(None, KVK_ANSI_V, False)
        if not ev_down or not ev_up:
            if ev_down:
                cf.CFRelease(ev_down)
            if ev_up:
                cf.CFRelease(ev_up)
            return False

        try:
            cg.CGEventSetFlags(ev_down, KCG_EVENT_FLAG_MASK_COMMAND)
            cg.CGEventSetFlags(ev_up, KCG_EVENT_FLAG_MASK_COMMAND)
            cg.CGEventPost(KCG_HID_EVENT_TAP, ev_down)
            time.sleep(0.015)
            cg.CGEventPost(KCG_HID_EVENT_TAP, ev_up)
            return True
        finally:
            cf.CFRelease(ev_down)
            cf.CFRelease(ev_up)
    except Exception:
        logger.debug("Quartz CGEvent paste failed, trying osascript fallback", exc_info=True)
        return False


def _paste_macos_osascript() -> bool:
    """Fallback Cmd+V paste on macOS via AppleScript System Events."""
    if sys.platform != "darwin":
        return False
    try:
        res = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using command down',
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def _paste_macos() -> bool:
    if sys.platform != "darwin":
        return False
    if not check_accessibility_permission():
        logger.warning(
            "macOS Accessibility permission not granted; skipping auto-paste (text kept in clipboard)."
        )
        return False
    if _paste_macos_quartz():
        return True
    return _paste_macos_osascript()


def _paste_linux(target_app: str = "") -> bool:
    """Paste on Linux supporting both Wayland (wtype/ydotool) and X11 (xdotool/pynput)."""
    use_shift = is_terminal_app(target_app)

    if is_wayland():
        wtype = shutil.which("wtype")
        if wtype:
            cmd = [wtype, "-M", "ctrl"]
            if use_shift:
                cmd.extend(["-M", "shift"])
            cmd.extend(["-k", "v"])
            if use_shift:
                cmd.extend(["-m", "shift"])
            cmd.extend(["-m", "ctrl"])
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=1.5, check=False)
                if res.returncode == 0:
                    return True
            except Exception:
                pass

        ydotool = shutil.which("ydotool")
        if ydotool:
            # Linux evdev keycodes: KEY_LEFTCTRL=29, KEY_LEFTSHIFT=42, KEY_V=47
            keys = (
                ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
                if use_shift
                else ["29:1", "47:1", "47:0", "29:0"]
            )
            try:
                res = subprocess.run(
                    [ydotool, "key", *keys],
                    capture_output=True,
                    timeout=1.5,
                    check=False,
                )
                if res.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    # X11 path: xdotool first, pynput fallback
    xdotool = shutil.which("xdotool")
    if xdotool:
        combo = "ctrl+shift+v" if use_shift else "ctrl+v"
        try:
            res = subprocess.run(
                [xdotool, "key", "--clearmodifiers", combo],
                capture_output=True,
                timeout=1.5,
                check=False,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

    try:
        from pynput.keyboard import Controller, Key

        kb = Controller()
        if use_shift:
            with kb.pressed(Key.ctrl, Key.shift):
                kb.tap("v")
        else:
            with kb.pressed(Key.ctrl):
                kb.tap("v")
        return True
    except Exception:
        logger.debug("Linux pynput paste fallback failed", exc_info=True)
        return False


def _type_directly_fallback(text: str) -> bool:
    """Optional direct keystroke typing fallback when clipboard paste cannot execute."""
    try:
        from pynput.keyboard import Controller

        kb = Controller()
        kb.type(text)
        return True
    except Exception:
        logger.debug("Direct typing fallback failed", exc_info=True)
        return False


def _default_clipboard_read() -> Optional[str]:
    try:
        return pyperclip.paste()
    except Exception:
        return None


def _default_clipboard_write(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        logger.exception("Failed to write text to clipboard")
        return False


class TextInjector:
    """Pastes Unicode text into the active window using OS-native paste with safe clipboard restore."""

    def __init__(
        self,
        restore_clipboard: bool = True,
        paste_delay_ms: int = 50,
        clipboard_restore_delay_ms: int = 450,
        direct_typing_fallback: bool = False,
        platform_name: Optional[str] = None,
        clipboard_read: Optional[Callable[[], Optional[str]]] = None,
        clipboard_write: Optional[Callable[[str], bool]] = None,
        paste_executor: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.restore_clipboard = restore_clipboard
        self.paste_delay_ms = paste_delay_ms
        self.clipboard_restore_delay_ms = max(150, int(clipboard_restore_delay_ms))
        self.direct_typing_fallback = direct_typing_fallback
        self._platform_name = platform_name
        self._clipboard_read = clipboard_read or _default_clipboard_read
        self._clipboard_write = clipboard_write or _default_clipboard_write
        self._paste_executor = paste_executor
        self.last_pasted: bool = False

    def _execute_os_paste(self, target_app: str = "") -> bool:
        if self._paste_executor is not None:
            return bool(self._paste_executor(target_app))
        plat = (self._platform_name or sys.platform).lower()
        if plat == "win32":
            return _paste_windows()
        if plat == "darwin":
            return _paste_macos()
        if plat.startswith("linux"):
            return _paste_linux(target_app=target_app)
        return False

    def copy_only(self, text: str) -> bool:
        """Copy text to the clipboard without simulating a paste keystroke."""
        if not text:
            return False
        self.last_pasted = False
        return bool(self._clipboard_write(text))

    def inject(self, text: str, target_app: str = "") -> bool:
        """Copy text and paste into active window. Returns True if injection succeeded.

        If paste fails, clipboard is intentionally NOT restored so the user never loses
        their dictated text and can manually press Cmd+V / Ctrl+V.
        """
        if not text:
            self.last_pasted = False
            return False

        previous_clipboard: Optional[str] = None
        if self.restore_clipboard:
            try:
                previous_clipboard = self._clipboard_read()
            except Exception:
                previous_clipboard = None

        if not self._clipboard_write(text):
            self.last_pasted = False
            if self.direct_typing_fallback:
                typed = _type_directly_fallback(text)
                self.last_pasted = typed
                return typed
            return False

        if self.paste_delay_ms > 0:
            time.sleep(max(0.015, self.paste_delay_ms / 1000.0))

        pasted_ok = self._execute_os_paste(target_app=target_app)

        if not pasted_ok and self.direct_typing_fallback:
            pasted_ok = _type_directly_fallback(text)

        self.last_pasted = pasted_ok

        # CRITICAL SAFETY: Only restore previous clipboard when paste actually succeeded
        # and the previous clipboard held actual text (empty string may indicate an image/file)!
        if pasted_ok and self.restore_clipboard and previous_clipboard:
            delay_sec = max(0.15, self.clipboard_restore_delay_ms / 1000.0)
            expected_norm = text.replace("\r\n", "\n")

            def _restore() -> None:
                time.sleep(delay_sec)
                try:
                    # Only restore if the user hasn't copied something else in the meantime
                    current_norm = (self._clipboard_read() or "").replace("\r\n", "\n")
                    if current_norm == expected_norm:
                        self._clipboard_write(previous_clipboard)
                except Exception:
                    pass

            threading.Thread(target=_restore, daemon=True).start()

        return pasted_ok
