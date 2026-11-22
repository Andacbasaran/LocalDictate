"""Clipboard-preserving text injection into the currently focused window."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time

import pyperclip

logger = logging.getLogger(__name__)

# Win32 SendInput constants and structures
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_MENU = 0x12  # Alt
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_V = 0x56


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


def _win32_send_key_events(events: list[tuple[int, int]]) -> None:
    """Send a sequence of (vk_code, flags) keyboard events via Win32 SendInput."""
    if os.name != "nt":
        return
    arr = (INPUT * len(events))()
    for i, (vk, flags) in enumerate(events):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    ctypes.windll.user32.SendInput(len(events), ctypes.byref(arr), ctypes.sizeof(INPUT))


def _release_modifiers_if_held() -> None:
    """Release any modifier keys that might still be held from the hotkey trigger."""
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    release_events: list[tuple[int, int]] = []
    for vk in (VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU, VK_LSHIFT, VK_RSHIFT):
        if user32.GetAsyncKeyState(vk) & 0x8000:
            release_events.append((vk, KEYEVENTF_KEYUP))
    if release_events:
        _win32_send_key_events(release_events)
        time.sleep(0.02)


class TextInjector:
    """Pastes Unicode text into the active window using clipboard + Ctrl+V."""

    def __init__(self, restore_clipboard: bool = True, paste_delay_ms: int = 50) -> None:
        self.restore_clipboard = restore_clipboard
        self.paste_delay_ms = paste_delay_ms

    def inject(self, text: str) -> None:
        if not text:
            return

        previous_clipboard: str | None = None
        if self.restore_clipboard:
            try:
                previous_clipboard = pyperclip.paste()
            except Exception:
                previous_clipboard = None

        try:
            pyperclip.copy(text)
        except Exception:
            logger.exception("Failed to copy transcribed text to clipboard")
            return

        time.sleep(max(0.02, self.paste_delay_ms / 1000.0))

        if os.name == "nt":
            _release_modifiers_if_held()
            _win32_send_key_events([
                (VK_CONTROL, 0),
                (VK_V, 0),
                (VK_V, KEYEVENTF_KEYUP),
                (VK_CONTROL, KEYEVENTF_KEYUP),
            ])
        else:
            logger.warning("Auto-paste SendInput is currently implemented for Windows only.")

        if self.restore_clipboard and previous_clipboard is not None:
            def _restore() -> None:
                time.sleep(0.22)
                try:
                    # Only restore if the user hasn't copied something else in the meantime
                    if pyperclip.paste() == text:
                        pyperclip.copy(previous_clipboard)
                except Exception:
                    pass

            threading.Thread(target=_restore, daemon=True).start()
