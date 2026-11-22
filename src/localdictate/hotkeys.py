"""Global keyboard hotkey listener supporting Toggle and Push-to-Talk modes."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from pynput import keyboard

logger = logging.getLogger(__name__)

# Maps generic modifier tokens to all specific pynput key names that satisfy them
MODIFIER_ALIASES: dict[str, set[str]] = {
    "ctrl": {"ctrl", "ctrl_l", "ctrl_r"},
    "alt": {"alt", "alt_l", "alt_r", "alt_gr"},
    "shift": {"shift", "shift_l", "shift_r"},
    "cmd": {"cmd", "cmd_l", "cmd_r"},
    "win": {"cmd", "cmd_l", "cmd_r"},
}

TOKEN_NORMALIZATION: dict[str, str] = {
    "control": "ctrl",
    "right_ctrl": "ctrl_r",
    "left_ctrl": "ctrl_l",
    "right_alt": "alt_r",
    "left_alt": "alt_l",
    "right_shift": "shift_r",
    "left_shift": "shift_l",
    "esc": "esc",
    "escape": "esc",
    "spacebar": "space",
}


def parse_hotkey(hotkey_str: str) -> list[str]:
    """Parse a human-readable hotkey like 'ctrl+alt+space' or 'ctrl_r' into normalized tokens."""
    tokens: list[str] = []
    for raw in hotkey_str.lower().replace(" ", "").split("+"):
        if not raw:
            continue
        tokens.append(TOKEN_NORMALIZATION.get(raw, raw))
    return tokens


def key_to_token(key: keyboard.Key | keyboard.KeyCode | None) -> str | None:
    """Convert a pynput key object into a canonical token string."""
    if key is None:
        return None
    if isinstance(key, keyboard.Key):
        return key.name.lower()
    if isinstance(key, keyboard.KeyCode):
        # Handle Ctrl+letter control characters (e.g. \x01..\x1a)
        if key.vk is not None:
            if 65 <= key.vk <= 90:  # A-Z
                return chr(key.vk).lower()
            if 48 <= key.vk <= 57:  # 0-9
                return chr(key.vk)
            if key.vk == 32:
                return "space"
        if key.char:
            return key.char.lower()
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
    """Listens globally for Toggle or Push-to-Talk hotkeys without blocking the OS."""

    def __init__(
        self,
        mode: str = "toggle",
        hotkey: str = "ctrl+alt+space",
        on_toggle: Callable[[], None] | None = None,
        on_ptt_start: Callable[[], None] | None = None,
        on_ptt_stop: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        self.mode = mode
        self.required_tokens = parse_hotkey(hotkey)
        self.on_toggle = on_toggle
        self.on_ptt_start = on_ptt_start
        self.on_ptt_stop = on_ptt_stop
        self.on_cancel = on_cancel

        self._lock = threading.Lock()
        self._pressed: set[str] = set()
        self._combo_active = False
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("HotkeyManager started: mode=%s tokens=%s", self.mode, self.required_tokens)

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
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

    def _handle_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        token = key_to_token(key)
        if token is None:
            return

        if token == "esc" and self.on_cancel is not None:
            self._fire(self.on_cancel)
            return

        trigger_toggle = False
        trigger_ptt_start = False

        with self._lock:
            self._pressed.add(token)
            if not self._combo_active and combo_matches(self.required_tokens, self._pressed):
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
        token = key_to_token(key)
        if token is None:
            return

        trigger_ptt_stop = False

        with self._lock:
            self._pressed.discard(token)
            if self._combo_active and not combo_matches(self.required_tokens, self._pressed):
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
