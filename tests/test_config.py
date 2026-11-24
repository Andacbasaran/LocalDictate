"""Tests for configuration persistence and defaults."""

from pathlib import Path

from localdictate.config import AppConfig, load_config, save_config
from localdictate.platform_utils import get_default_hotkeys


def test_default_config_values():
    expected_toggle, expected_ptt = get_default_hotkeys()
    cfg = AppConfig()
    assert cfg.hotkey_mode == "toggle"
    assert cfg.toggle_hotkey == expected_toggle
    assert cfg.ptt_hotkey == expected_ptt
    assert cfg.model_size == "small"
    assert cfg.compute_type == "int8"
    assert cfg.offline_only is True
    assert cfg.active_hotkey == expected_toggle

    cfg.hotkey_mode = "push_to_talk"
    assert cfg.active_hotkey == expected_ptt


def test_save_and_load_roundtrip(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    original = AppConfig(
        hotkey_mode="push_to_talk",
        ptt_hotkey="f9",
        model_size="medium",
        language="tr",
        vad_filter=False,
        restore_clipboard=False,
    )
    save_config(original, cfg_path)
    loaded = load_config(cfg_path)
    assert loaded == original


def test_load_ignores_unknown_keys_and_handles_missing_file(tmp_path: Path):
    missing = tmp_path / "does_not_exist.json"
    assert load_config(missing) == AppConfig()

    cfg_path = tmp_path / "extra.json"
    cfg_path.write_text('{"model_size": "base", "unknown_future_field": 123}', encoding="utf-8")
    loaded = load_config(cfg_path)
    assert loaded.model_size == "base"
    assert loaded.compute_type == "int8"
