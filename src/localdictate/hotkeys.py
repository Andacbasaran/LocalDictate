"""Global keyboard hotkey listener supporting Toggle and Push-to-Talk modes across Win/macOS/Linux."""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Callable, Optional

from pynput import keyboard

logger = logging.getLogger(__name__)

# Maps generic modifier tokens to all specific pynput key names that satisfy them
MODIFIER_ALIASES: dict[str, set[str]] = {
    "ctrl": {"ctrl", "ctrl_l", "ctrl_r"},
    "alt": {"alt", "alt_l", "alt_r", "alt_gr"},
    "shift": {"shift", "shift_l", "shift_r"},
    "cmd": {"cmd", "cmd_l", "cmd_r"},
    "win": {"cmd", "cmd_l", "cmd_r"},
    "option": {"alt", "alt_l", "alt_r", "alt_gr"},
}

TOKEN_NORMALIZATION: dict[str, str] = {
    "control": "ctrl",
    "right_ctrl": "ctrl_r",
    "left_ctrl": "ctrl_l",
    "right_alt": "alt_r",
    "left_alt": "alt_l",
    "right_option": "alt_r",
    "left_option": "alt_l",
    "opt": "alt",
    "option": "alt",
    "right_shift": "shift_r",
    "left_shift": "shift_l",
    "right_cmd": "cmd_r",
    "left_cmd": "cmd_l",
    "command": "cmd",
    "super": "cmd",
    "meta": "cmd",
    "esc": "esc",
    "escape": "esc",
    "spacebar": "space",
}

# macOS Carbon virtual keycodes (HIToolbox/Events.h) used when Option/Ctrl transforms key.char
MACOS_CARBON_VK_MAP: dict[int, str] = {
    0x00: "a",
    0x01: "s",
    0x02: "d",
    0x03: "f",
    0x04: "h",
    0x05: "g",
    0x06: "z",
    0x07: "x",
    0x08: "c",
    0x09: "v",
    0x0B: "b",
    0x0C: "q",
    0x0D: "w",
    0x0E: "e",
    0x0F: "r",
    0x10: "y",
    0x11: "t",
    0x12: "1",
    0x13: "2",
    0x14: "3",
    0x15: "4",
    0x16: "6",
    0x17: "5",
    0x19: "9",
    0x1A: "7",
    0x1C: "8",
    0x1D: "0",
    0x1F: "o",
    0x20: "u",
    0x22: "i",
    0x23: "p",
    0x25: "l",
    0x26: "j",
    0x28: "k",
    0x2D: "n",
    0x2E: "m",
    0x31: "space",
    0x35: "esc",
    0x60: "f5",
    0x61: "f6",
    0x62: "f7",
    0x64: "f8",
    0x65: "f9",
    0x6D: "f10",
    0x67: "f11",
    0x6F: "f12",
}


def parse_hotkey(hotkey_str: str) -> list[str]:
    """Parse a human-readable hotkey like 'ctrl+alt+space' or 'alt_r' into normalized tokens."""
    tokens: list[str] = []
    for raw in hotkey_str.lower().replace(" ", "").split("+"):
        if not raw:
            continue
        tokens.append(TOKEN_NORMALIZATION.get(raw, raw))
    return tokens


def format_hotkey_display(hotkey_str: str, platform_name: Optional[str] = None) -> str:
    """Render a hotkey string into crisp, OS-idiomatic keycap labels."""
    plat = (platform_name or sys.platform).lower()
    tokens = parse_hotkey(hotkey_str)
    if not tokens:
        return ""
    is_mac = plat == "darwin"
    labels: list[str] = []
    for tok in tokens:
        if tok == "ctrl":
            labels.append("⌃" if is_mac else "Ctrl")
        elif tok == "ctrl_r":
            labels.append("Right ⌃" if is_mac else "Right Ctrl")
        elif tok == "ctrl_l":
            labels.append("Left ⌃" if is_mac else "Left Ctrl")
        elif tok == "alt":
            labels.append("⌥" if is_mac else "Alt")
        elif tok == "alt_r":
            labels.append("Right ⌥" if is_mac else "Right Alt")
        elif tok == "alt_l":
            labels.append("Left ⌥" if is_mac else "Left Alt")
        elif tok == "shift":
            labels.append("⇧" if is_mac else "Shift")
        elif tok == "cmd":
            labels.append("⌘" if is_mac else "Win")
        elif tok == "space":
            labels.append("Space")
        elif tok == "esc":
            labels.append("Esc")
        else:
            labels.append(tok.upper() if len(tok) <= 3 else tok.capitalize())
    return " + ".join(labels)


def key_to_token(
    key: keyboard.Key | keyboard.KeyCode | None,
    platform_name: Optional[str] = None,
) -> str | None:
    """Convert a pynput key object into a canonical token string safely across OSes.

    Guards Windows VK numeric ranges strictly to win32 so macOS Carbon keycodes
    (e.g. vk=49 for Space) and X11 keysyms are never corrupted into digits or letters.
    """
    if key is None:
        return None
    if isinstance(key, keyboard.Key):
        return key.name.lower()

    if isinstance(key, keyboard.KeyCode):
        plat = (platform_name or sys.platform).lower()

        if plat == "win32":
            if key.vk is not None:
                if 65 <= key.vk <= 90:  # Windows VK_A .. VK_Z
                    return chr(key.vk).lower()
                if 48 <= key.vk <= 57:  # Windows VK_0 .. VK_9
                    return chr(key.vk)
                if key.vk == 32:  # Windows VK_SPACE
                    return "space"
                if 112 <= key.vk <= 123:  # Windows VK_F1 .. VK_F12
                    return f"f{key.vk - 111}"
            if key.char:
                if key.char == " ":
                    return "space"
                return key.char.lower()
            return None

        if plat == "darwin":
            # Prefer Carbon keycode mapping first so Option+Space (\xa0) or Option+letter resolves reliably
            if key.vk is not None and key.vk in MACOS_CARBON_VK_MAP:
                return MACOS_CARBON_VK_MAP[key.vk]
            if key.char:
                if key.char in (" ", "\xa0"):
                    return "space"
                # Handle Ctrl+A .. Ctrl+Z control characters
                code = ord(key.char)
                if 1 <= code <= 26:
                    return chr(code + 96)
                if key.char.isprintable():
                    return key.char.lower()
            return None

        # Linux / X11 / Wayland
        if key.char:
            if key.char == " ":
                return "space"
            code = ord(key.char)
            if 1 <= code <= 26:
                return chr(code + 96)
            if key.char.isprintable():
                return key.char.lower()
        if key.vk is not None:
            if key.vk == 0x20:
                return "space"
            if 0xFFBE <= key.vk <= 0xFFC9:  # X11 XK_F1 .. XK_F12
                return f"f{key.vk - 0xFFBD}"
            if 0x61 <= key.vk <= 0x7A:  # X11 lowercase a..z keysyms
                return chr(key.vk)
            if 0x41 <= key.vk <= 0x5A:  # X11 uppercase A..Z keysyms
                return chr(key.vk).lower()
            if 0x30 <= key.vk <= 0x39:  # X11 0..9 keysyms
                return chr(key.vk)
    return None


def combo_matches(required_tokens: list[str], pressed_tokens: set[str]) -> bool:
    """Return True if all required hotkey tokens are currently held down."""
    if not required_tokens:
        return False
    for req in required_tokens:
        if req in MODIFIER_ALIASES:
            if not (pressed_tokens & MODIFIER_ALIASES[req]):
                return False
        else:
            if req not in pressed_tokens:
                return False
    return True


class HotkeyManager:
    """Listens globally for Toggle or Push-to-Talk hotkeys without blocking or crashing the OS."""

    def __init__(
        self,
        mode: str = "toggle",
        hotkey: str = "ctrl+alt+space",
        on_toggle: Callable[[], None] | None = None,
        on_ptt_start: Callable[[], None] | None = None,
        on_ptt_stop: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        stale_timeout_sec: float = 12.0,
        platform_name: Optional[str] = None,
    ) -> None:
        self.mode = mode
        self.required_tokens = parse_hotkey(hotkey)
        self.on_toggle = on_toggle
        self.on_ptt_start = on_ptt_start
        self.on_ptt_stop = on_ptt_stop
        self.on_cancel = on_cancel
        self.stale_timeout_sec = max(1.0, float(stale_timeout_sec))
        self._platform_name = platform_name

        self._lock = threading.Lock()
        self._pressed: dict[str, float] = {}
        self._combo_active = False
        self._listener: keyboard.Listener | None = None
        self.is_running: bool = False
        self.listener_error: str | None = None

    def start(self) -> bool:
        """Start the global hotkey listener. Returns False gracefully if blocked by OS permissions."""
        if self._listener is not None and self.is_running:
            return True
        self.listener_error = None
        try:
            listener = keyboard.Listener(
                on_press=self._handle_press,
                on_release=self._handle_release,
            )
            listener.daemon = True
            listener.start()
            self._listener = listener
            self.is_running = True
            logger.info("HotkeyManager started: mode=%s tokens=%s", self.mode, self.required_tokens)
            return True
        except Exception as exc:
            self._listener = None
            self.is_running = False
            self.listener_error = str(exc)
            logger.warning(
                "Global hotkey listener unavailable (%s); use Studio Start/Stop button instead.",
                exc,
            )
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self.is_running = False
        with self._lock:
            self._pressed.clear()
            self._combo_active = False

    def reset_stuck_keys(self) -> None:
        """Force-clear all tracked pressed keys (e.g. after sleep/wake or window switch)."""
        with self._lock:
            self._pressed.clear()
            self._combo_active = False

    def update(self, mode: str, hotkey: str) -> None:
        with self._lock:
            self.mode = mode
            self.required_tokens = parse_hotkey(hotkey)
            self._pressed.clear()
            self._combo_active = False
        logger.info("HotkeyManager updated: mode=%s tokens=%s", self.mode, self.required_tokens)

    def _prune_stale_locked(self, now: float) -> None:
        """Remove keys whose release event was likely dropped during sleep/lock or UAC prompt."""
        if not self._pressed:
            return
        # Never prune an active PTT combo while the user is actively holding it to dictate
        if self.mode == "push_to_talk" and self._combo_active:
            return
        stale = [
            tok
            for tok, ts in self._pressed.items()
            if (now - ts) > self.stale_timeout_sec
        ]
        for tok in stale:
            self._pressed.pop(tok, None)
        if stale and not combo_matches(self.required_tokens, set(self._pressed.keys())):
            self._combo_active = False

    def _handle_press(
        self,
        key: keyboard.Key | keyboard.KeyCode | None,
        now: Optional[float] = None,
    ) -> None:
        token = key_to_token(key, platform_name=self._platform_name)
        if token is None:
            return

        if token == "esc" and self.on_cancel is not None:
            self._fire(self.on_cancel)
            return

        ts = time.monotonic() if now is None else now
        trigger_toggle = False
        trigger_ptt_start = False

        with self._lock:
            self._prune_stale_locked(ts)
            self._pressed[token] = ts
            pressed_set = set(self._pressed.keys())
            if not self._combo_active and combo_matches(self.required_tokens, pressed_set):
                self._combo_active = True
                if self.mode == "push_to_talk":
                    trigger_ptt_start = True
                else:
                    trigger_toggle = True

        if trigger_toggle and self.on_toggle is not None:
            self._fire(self.on_toggle)
        elif trigger_ptt_start and self.on_ptt_start is not None:
            self._fire(self.on_ptt_start)

    def _handle_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        token = key_to_token(key, platform_name=self._platform_name)
        if token is None:
            return

        trigger_ptt_stop = False

        with self._lock:
            self._pressed.pop(token, None)
            pressed_set = set(self._pressed.keys())
            if self._combo_active and not combo_matches(self.required_tokens, pressed_set):
                self._combo_active = False
                if self.mode == "push_to_talk":
                    trigger_ptt_stop = True

        if trigger_ptt_stop and self.on_ptt_stop is not None:
            self._fire(self.on_ptt_stop)

    @staticmethod
    def _fire(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            logger.exception("Error in hotkey callback")
