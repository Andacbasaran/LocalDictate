"""Regression tests for LocalDictate P0/P1 concurrency, text safety, and security fixes."""

from __future__ import annotations

import csv
import os
import sqlite3
import threading
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from localdictate.config import AppConfig, load_config, save_config
from localdictate.history import HistoryStore
from localdictate.hotkeys import HotkeyManager, format_hotkey_display
from localdictate.platform_utils import infer_mode_for_app, is_terminal_app
from localdictate.postprocess import (
    OfflineLockError,
    TextPostProcessor,
    _NoRedirectHandler,
    is_localhost_url,
    normalize_spacing,
)
from localdictate.snippets import (
    STARTER_PACKS,
    apply_replacements,
    apply_voice_commands,
    build_safe_term_pattern,
)
from localdictate.ui.studio_window import _format_rules_text, _parse_rules_text
from localdictate.updater import (
    UpdateInfo,
    download_update_asset,
    is_newer_version,
    is_trusted_update_url,
    select_platform_asset,
)


def test_normalize_spacing_and_voice_commands_preserve_code_syntax() -> None:
    assert normalize_spacing("check .env file") == "check .env file"
    assert normalize_spacing("use std::vector and ../src/main.py") == "use std::vector and ../src/main.py"
    assert apply_voice_commands("use std::vector and ../src/main.py") == "use std::vector and ../src/main.py"
    assert apply_voice_commands("wait... really?") == "wait... really?"
    assert apply_voice_commands("during this period of time") == "during this period of time"
    # Explicit end-of-utterance 'period' still converts cleanly
    assert apply_voice_commands("hello world period") == "hello world."

    proc = TextPostProcessor(AppConfig(snippets={".env": "`.env`"}))
    res = proc.process("check .env file")
    assert res.final_text == "check `.env` file"


def test_lazy_clipboard_snippet_expansion_and_empty_term_guard() -> None:
    clipboard_reads = 0

    def _clip() -> str:
        nonlocal clipboard_reads
        clipboard_reads += 1
        return "SECRET"

    out = apply_replacements(
        "hello normal dictation",
        {"paste link": "Link: {{clipboard}}"},
        clipboard_getter=_clip,
    )
    assert out == "hello normal dictation"
    assert clipboard_reads == 0

    with pytest.raises(ValueError):
        build_safe_term_pattern("   ")


def test_multiline_snippets_roundtrip_via_studio_rules_parser() -> None:
    dev_pack = STARTER_PACKS["developer"]
    assert "\n" in dev_pack["pr checklist"]
    formatted = _format_rules_text(dev_pack)
    parsed = _parse_rules_text(formatted)
    assert parsed["pr checklist"] == dev_pack["pr checklist"]
    assert parsed["daily standup"] == dev_pack["daily standup"]


def test_offline_lock_strict_localhost_and_redirect_blocking() -> None:
    assert is_localhost_url("http://localhost:11434") is True
    assert is_localhost_url("http://127.0.0.1:1234/v1") is True
    assert is_localhost_url("http://[::1]:11434") is True
    assert is_localhost_url("file://localhost/etc/passwd") is False
    assert is_localhost_url("ftp://localhost/file") is False
    assert is_localhost_url("http://0.0.0.0:11434") is False

    handler = _NoRedirectHandler()
    with pytest.raises(OfflineLockError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example.com")


def test_updater_fail_closed_url_allowlist_and_arch_matching(tmp_path: Path) -> None:
    assert is_trusted_update_url("https://github.com/Andacbasaran/LocalDictate/releases/latest") is True
    assert is_trusted_update_url("http://github.com/Andacbasaran/LocalDictate/releases/latest") is False
    assert is_trusted_update_url("file:///etc/passwd") is False
    assert is_trusted_update_url("https://evil.example.com/setup.exe") is False

    assert is_newer_version("1.0.0-beta.2", "1.0.0-beta.1") is True
    assert is_newer_version("1.0.0+build.5", "1.0.0-rc.1") is True

    arm_only = [
        {
            "name": "LocalDictate-v1.1.0-macOS-arm64.dmg",
            "browser_download_url": "https://github.com/Andacbasaran/LocalDictate/releases/download/v1.1.0/LocalDictate-v1.1.0-macOS-arm64.dmg",
            "size": 1000,
        },
        {
            "name": "SHA256SUMS.txt",
            "browser_download_url": "https://github.com/Andacbasaran/LocalDictate/releases/download/v1.1.0/SHA256SUMS.txt",
            "size": 100,
        },
    ]
    assert select_platform_asset(arm_only, platform_name="darwin", machine="x86_64")[0] == ""

    info_no_cs = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/LocalDictate/releases/tag/v1.1.0",
        asset_name="LocalDictate-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://github.com/Andacbasaran/LocalDictate/releases/download/v1.1.0/LocalDictate-Setup-v1.1.0-Windows-x64.exe",
        checksum_url="",
    )
    with pytest.raises(RuntimeError, match="SHA-256"):
        download_update_asset(info_no_cs, str(tmp_path))

    info_ok = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/LocalDictate/releases/tag/v1.1.0",
        asset_name="LocalDictate-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://github.com/Andacbasaran/LocalDictate/releases/download/v1.1.0/LocalDictate-Setup-v1.1.0-Windows-x64.exe",
        checksum_url="https://github.com/Andacbasaran/LocalDictate/releases/download/v1.1.0/SHA256SUMS.txt",
    )
    asset_resp = MagicMock()
    asset_resp.headers = {"Content-Length": "4"}
    asset_resp.read.side_effect = [b"data", b""]
    asset_resp.__enter__.return_value = asset_resp
    sums_resp = MagicMock()
    sums_resp.__enter__.return_value = BytesIO(b"")
    with patch("localdictate.updater.urllib.request.urlopen", side_effect=[asset_resp, sums_resp]):
        with pytest.raises(RuntimeError, match="SHA-256"):
            download_update_asset(info_ok, str(tmp_path))


def test_history_csv_formula_protection_like_escape_and_closed_guard(tmp_path: Path) -> None:
    store = HistoryStore(db_path=tmp_path / "hist.db")
    store.add(
        raw_text="- bullet item",
        final_text="- bullet item",
        language="en",
        model_size="small",
        audio_duration_sec=1.0,
        inference_sec=0.1,
        target_app="=CMD()",
    )
    store.add(
        raw_text="normal snake_case 100% value",
        final_text="normal snake_case 100% value",
        language="en",
        model_size="small",
        audio_duration_sec=1.0,
        inference_sec=0.1,
        target_app="Notes",
    )

    # LIKE wildcard escaping: '_' and '%' must match literally, not everything
    assert len(store.list_recent(query="100%")) == 1
    assert len(store.list_recent(query="snake_case")) == 1
    assert len(store.list_recent(query="___")) == 0

    csv_path = store.export_entries(tmp_path / "out.csv", fmt="csv")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    # Header + 2 rows; dangerous cells must be prefixed with leading apostrophe
    all_cells = [c for row in rows[1:] for c in row]
    assert "'- bullet item" in all_cells
    assert "'=CMD()" in all_cells

    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store.list_recent()


def test_platform_utils_no_false_positive_substrings() -> None:
    assert is_terminal_app("sun-awt-X11") is False
    assert is_terminal_app("wt") is True
    assert is_terminal_app("WindowsTerminal") is True
    assert infer_mode_for_app("Adobe Media Encoder") == "cleanup"
    assert infer_mode_for_app("Barcode Scanner") == "cleanup"
    assert infer_mode_for_app("Visual Studio Code") == "code"
    assert infer_mode_for_app("Code") == "code"


def test_hotkey_manager_async_dispatch_does_not_block_hook_thread() -> None:
    started = threading.Event()
    release = threading.Event()

    def _slow_cb() -> None:
        started.set()
        release.wait(timeout=2.0)

    mgr = HotkeyManager(
        mode="toggle",
        hotkey="ctrl+alt+space",
        on_toggle=_slow_cb,
        dispatch_async=True,
    )
    from pynput import keyboard

    t0 = time.monotonic()
    mgr._handle_press(keyboard.Key.ctrl_l)
    mgr._handle_press(keyboard.Key.alt_l)
    mgr._handle_press(keyboard.Key.space)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2
    assert started.wait(timeout=1.0)
    release.set()
    mgr.flush(timeout=1.0)
    mgr.stop()
    assert "Shift" in format_hotkey_display("shift_r", platform_name="win32")
    assert "⇧" in format_hotkey_display("shift_r", platform_name="darwin")


def test_config_atomic_save_permissions_and_corrupt_backup(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    save_config(AppConfig(model_size="base"), path=cfg_path)
    if os.name == "posix":
        assert (cfg_path.stat().st_mode & 0o777) == 0o600

    cfg_path.write_text("{broken json", encoding="utf-8")
    loaded = load_config(path=cfg_path)
    assert isinstance(loaded, AppConfig)
    assert (tmp_path / "config.json.corrupt.bak").exists()
