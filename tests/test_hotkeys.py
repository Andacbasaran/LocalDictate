"""Tests for global hotkey parsing and Toggle / Push-to-Talk state transitions."""

from pynput import keyboard

from localdictate.hotkeys import HotkeyManager, combo_matches, parse_hotkey


def test_parse_hotkey_normalizes_aliases():
    assert parse_hotkey("Ctrl + Alt + Space") == ["ctrl", "alt", "space"]
    assert parse_hotkey("right_ctrl") == ["ctrl_r"]
    assert parse_hotkey("F9") == ["f9"]


def test_combo_matches_generic_vs_specific_modifiers():
    assert combo_matches(["ctrl", "alt", "space"], {"ctrl_l", "alt_l", "space"})
    assert combo_matches(["ctrl", "alt", "space"], {"ctrl_r", "alt_gr", "space"})
    assert not combo_matches(["ctrl", "alt", "space"], {"ctrl_l", "space"})

    assert combo_matches(["ctrl_r"], {"ctrl_r"})
    assert not combo_matches(["ctrl_r"], {"ctrl_l"})


def test_toggle_mode_debounces_key_repeat():
    events: list[str] = []
    mgr = HotkeyManager(
        mode="toggle",
        hotkey="ctrl+alt+space",
        on_toggle=lambda: events.append("toggle"),
        on_cancel=lambda: events.append("cancel"),
    )

    mgr._handle_press(keyboard.Key.ctrl_l)
    mgr._handle_press(keyboard.Key.alt_l)
    mgr._handle_press(keyboard.Key.space)
    # Simulated OS key-repeat while still held
    mgr._handle_press(keyboard.Key.space)
    assert events == ["toggle"]

    mgr._handle_release(keyboard.Key.space)
    mgr._handle_press(keyboard.Key.space)
    assert events == ["toggle", "toggle"]

    mgr._handle_press(keyboard.Key.esc)
    assert events == ["toggle", "toggle", "cancel"]


def test_push_to_talk_mode_starts_and_stops_on_release():
    events: list[str] = []
    mgr = HotkeyManager(
        mode="push_to_talk",
        hotkey="ctrl_r",
        on_ptt_start=lambda: events.append("start"),
        on_ptt_stop=lambda: events.append("stop"),
    )

    # Left ctrl must not trigger Right ctrl PTT
    mgr._handle_press(keyboard.Key.ctrl_l)
    mgr._handle_release(keyboard.Key.ctrl_l)
    assert events == []

    # Holding Right ctrl fires start once, releasing fires stop once
    mgr._handle_press(keyboard.Key.ctrl_r)
    mgr._handle_press(keyboard.Key.ctrl_r)
    assert events == ["start"]

    mgr._handle_release(keyboard.Key.ctrl_r)
    assert events == ["start", "stop"]
