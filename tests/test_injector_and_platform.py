"""Comprehensive cross-platform unit tests for injector, hotkeys, platform_utils,
autostart, hardware, updater, i18n, snippets, voice commands, and history."""

from __future__ import annotations

import plistlib
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pynput import keyboard

from localdictate.autostart import (
    get_linux_desktop_path,
    get_macos_plist_path,
    is_autostart_enabled,
    set_autostart,
)
from localdictate.hardware import (
    PROFILE_AUTO,
    PROFILE_BALANCED,
    PROFILE_ECO,
    PROFILE_PERFORMANCE,
    HardwareProfile,
    classify_hardware_tier,
    compute_runtime_tuning,
    format_hardware_summary,
    get_os_data_dir,
    normalize_arch,
    select_compute_type_candidates,
)
from localdictate.history import HistoryStore, normalize_search_text
from localdictate.hotkeys import HotkeyManager, format_hotkey_display, key_to_token
from localdictate.i18n import TRANSLATIONS, LanguageManager, tr
from localdictate.injector import TextInjector, _paste_linux
from localdictate.platform_utils import (
    get_default_hotkeys,
    get_platform_id,
    infer_mode_for_app,
    is_terminal_app,
    is_wayland,
)
from localdictate.postprocess import OfflineLockError, fetch_llm_models, is_localhost_url
from localdictate.snippets import (
    apply_replacements,
    apply_voice_commands,
    build_safe_term_pattern,
    expand_snippet_templates,
    merge_starter_pack,
)
from localdictate.updater import (
    check_for_updates,
    compute_file_sha256,
    is_newer_version,
    parse_semver,
    parse_sha256sums,
    select_platform_asset,
    verify_file_sha256,
)

# ═══════════════════════════════════════════════════════════════════════════
# 1. TEXT INJECTOR & CLIPBOARD SAFETY GUARANTEES
# ═══════════════════════════════════════════════════════════════════════════


def test_injector_never_restores_clipboard_when_paste_fails():
    """Critical safety guarantee: dictated text stays in clipboard if OS paste fails."""
    clipboard = {"value": "previous user clipboard"}

    def read_cb() -> str:
        return clipboard["value"]

    def write_cb(text: str) -> bool:
        clipboard["value"] = text
        return True

    injector = TextInjector(
        restore_clipboard=True,
        paste_delay_ms=0,
        clipboard_restore_delay_ms=150,
        clipboard_read=read_cb,
        clipboard_write=write_cb,
        paste_executor=lambda _app: False,
    )

    ok = injector.inject("Critical dictated paragraph", target_app="VS Code")
    assert ok is False
    assert injector.last_pasted is False
    assert clipboard["value"] == "Critical dictated paragraph"

    # Wait longer than clipboard_restore_delay_ms to prove NO background thread clobbers it
    time.sleep(0.28)
    assert clipboard["value"] == "Critical dictated paragraph"


def test_injector_restores_clipboard_when_paste_succeeds():
    clipboard = {"value": "original clipboard"}
    pasted_targets: list[str] = []

    def read_cb() -> str:
        return clipboard["value"]

    def write_cb(text: str) -> bool:
        clipboard["value"] = text
        return True

    def paste_cb(target_app: str) -> bool:
        pasted_targets.append(target_app)
        return True

    injector = TextInjector(
        restore_clipboard=True,
        paste_delay_ms=0,
        clipboard_restore_delay_ms=150,
        clipboard_read=read_cb,
        clipboard_write=write_cb,
        paste_executor=paste_cb,
    )

    ok = injector.inject("Hello world", target_app="Terminal")
    assert ok is True
    assert injector.last_pasted is True
    assert pasted_targets == ["Terminal"]

    deadline = time.monotonic() + 1.0
    while clipboard["value"] != "original clipboard" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert clipboard["value"] == "original clipboard"


def test_injector_does_not_overwrite_newer_user_clipboard_on_restore():
    clipboard = {"value": "before dictation"}

    injector = TextInjector(
        restore_clipboard=True,
        paste_delay_ms=0,
        clipboard_restore_delay_ms=180,
        clipboard_read=lambda: clipboard["value"],
        clipboard_write=lambda t: (clipboard.__setitem__("value", t) or True),
        paste_executor=lambda _app: True,
    )

    assert injector.inject("dictated text") is True
    # User copies something new before restore timer fires
    clipboard["value"] = "newly copied secret"
    time.sleep(0.28)
    assert clipboard["value"] == "newly copied secret"


def test_injector_copy_only_and_empty_text():
    clipboard = {"value": "init"}
    paste_called = []

    injector = TextInjector(
        clipboard_read=lambda: clipboard["value"],
        clipboard_write=lambda t: (clipboard.__setitem__("value", t) or True),
        paste_executor=lambda _app: (paste_called.append(True) or True),
    )

    assert injector.inject("") is False
    assert injector.copy_only("") is False
    assert clipboard["value"] == "init"

    assert injector.copy_only("copied only") is True
    assert clipboard["value"] == "copied only"
    assert paste_called == []
    assert injector.last_pasted is False


def test_injector_direct_typing_fallback_when_paste_fails():
    clipboard = {"value": "old"}
    injector = TextInjector(
        restore_clipboard=True,
        paste_delay_ms=0,
        direct_typing_fallback=True,
        clipboard_read=lambda: clipboard["value"],
        clipboard_write=lambda t: (clipboard.__setitem__("value", t) or True),
        paste_executor=lambda _app: False,
    )

    with patch("localdictate.injector._type_directly_fallback", return_value=True) as mock_type:
        ok = injector.inject("typed fallback")
        assert ok is True
        assert injector.last_pasted is True
        mock_type.assert_called_once_with("typed fallback")


def test_paste_linux_wayland_and_x11_terminal_shift():
    fake_ok = SimpleNamespace(returncode=0)

    with (
        patch("localdictate.injector.is_wayland", return_value=True),
        patch("localdictate.injector.shutil.which", side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None),
        patch("localdictate.injector.subprocess.run", return_value=fake_ok) as mock_run,
    ):
        assert _paste_linux(target_app="kitty") is True
        cmd = mock_run.call_args[0][0]
        assert "-M" in cmd and "shift" in cmd and "ctrl" in cmd

    with (
        patch("localdictate.injector.is_wayland", return_value=False),
        patch("localdictate.injector.shutil.which", side_effect=lambda cmd: "/usr/bin/xdotool" if cmd == "xdotool" else None),
        patch("localdictate.injector.subprocess.run", return_value=fake_ok) as mock_run,
    ):
        assert _paste_linux(target_app="Alacritty") is True
        assert "ctrl+shift+v" in mock_run.call_args[0][0]

        assert _paste_linux(target_app="Firefox") is True
        assert "ctrl+v" in mock_run.call_args[0][0]


# ═══════════════════════════════════════════════════════════════════════════
# 2. MACOS CARBON VK GUARD VS WIN32 / LINUX HOTKEYS
# ═══════════════════════════════════════════════════════════════════════════


def test_macos_vk_code_guard_vs_win32_and_linux():
    # Carbon VK 49 (0x31) is Space on macOS, whereas Win32 VK 49 is '1'
    space_or_one = keyboard.KeyCode.from_vk(49)
    assert key_to_token(space_or_one, platform_name="darwin") == "space"
    assert key_to_token(space_or_one, platform_name="win32") == "1"

    # Carbon VK 0x00 is 'a', 0x09 is 'v', Option+Space emits non-breaking space \xa0
    assert key_to_token(keyboard.KeyCode.from_vk(0x00), platform_name="darwin") == "a"
    assert key_to_token(keyboard.KeyCode.from_vk(0x09), platform_name="darwin") == "v"
    assert key_to_token(keyboard.KeyCode(char="\xa0", vk=0x31), platform_name="darwin") == "space"

    # Win32 VK ranges
    assert key_to_token(keyboard.KeyCode.from_vk(65), platform_name="win32") == "a"
    assert key_to_token(keyboard.KeyCode.from_vk(32), platform_name="win32") == "space"
    assert key_to_token(keyboard.KeyCode.from_vk(120), platform_name="win32") == "f9"

    # Linux X11 keysyms
    assert key_to_token(keyboard.KeyCode.from_vk(0xFFBE), platform_name="linux") == "f1"
    assert key_to_token(keyboard.KeyCode.from_vk(0x61), platform_name="linux") == "a"
    assert key_to_token(keyboard.KeyCode(char=" "), platform_name="linux") == "space"


def test_format_hotkey_display_os_specific():
    assert format_hotkey_display("alt+space", platform_name="darwin") == "⌥ + Space"
    assert format_hotkey_display("alt_r", platform_name="darwin") == "Right ⌥"
    assert format_hotkey_display("ctrl+alt+space", platform_name="win32") == "Ctrl + Alt + Space"
    assert format_hotkey_display("ctrl_r", platform_name="linux") == "Right Ctrl"


def test_hotkey_manager_stale_pruning_and_ptt_protection():
    events: list[str] = []
    mgr = HotkeyManager(
        mode="toggle",
        hotkey="ctrl+alt+space",
        on_toggle=lambda: events.append("toggle"),
        stale_timeout_sec=2.0,
        platform_name="linux",
    )
    mgr._handle_press(keyboard.Key.ctrl_l, now=10.0)
    mgr._handle_press(keyboard.Key.alt_l, now=10.0)
    # 5 seconds later, ctrl_l and alt_l are pruned so pressing space alone must not fire
    mgr._handle_press(keyboard.Key.space, now=15.0)
    assert events == []

    # Active PTT hold must NOT be pruned while held
    ptt_events: list[str] = []
    ptt = HotkeyManager(
        mode="push_to_talk",
        hotkey="alt_r",
        on_ptt_start=lambda: ptt_events.append("start"),
        on_ptt_stop=lambda: ptt_events.append("stop"),
        stale_timeout_sec=1.0,
        platform_name="darwin",
    )
    ptt._handle_press(keyboard.Key.alt_r, now=10.0)
    assert ptt_events == ["start"]
    ptt._handle_press(keyboard.Key.shift_l, now=25.0)
    assert ptt._combo_active is True
    ptt._handle_release(keyboard.Key.alt_r)
    assert ptt_events == ["start", "stop"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. PLATFORM UTILS
# ═══════════════════════════════════════════════════════════════════════════


def test_platform_utils_defaults_and_app_routing(monkeypatch):
    assert get_platform_id("win32") == "windows"
    assert get_platform_id("darwin") == "macos"
    assert get_platform_id("linux") == "linux"

    assert get_default_hotkeys("darwin") == ("alt+space", "alt_r")
    assert get_default_hotkeys("win32") == ("ctrl+alt+space", "ctrl_r")
    assert get_default_hotkeys("linux") == ("ctrl+alt+space", "ctrl_r")

    assert is_terminal_app("iTerm2") is True
    assert is_terminal_app("WindowsTerminal") is True
    assert is_terminal_app("gnome-terminal") is True
    assert is_terminal_app("Slack") is False

    assert infer_mode_for_app("Visual Studio Code") == "code"
    assert infer_mode_for_app("Apple Mail") == "formal"
    assert infer_mode_for_app("Slack") == "concise"
    assert infer_mode_for_app("Obsidian") == "bullet_notes"
    assert infer_mode_for_app("Unknown App", default_mode="cleanup") == "cleanup"
    assert infer_mode_for_app(
        "My Custom Writer",
        custom_rules={"writer": "formal", "custom writer": "concise"},
    ) == "concise"

    monkeypatch.setattr("localdictate.platform_utils.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    assert is_wayland() is True

    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert is_wayland() is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. AUTOSTART (ISOLATED IN TMP_PATH)
# ═══════════════════════════════════════════════════════════════════════════


def test_autostart_macos_plist_and_linux_desktop(tmp_path: Path):
    mac_dir = tmp_path / "LaunchAgents"
    assert is_autostart_enabled(platform_name="darwin", base_dir=mac_dir) is False
    assert set_autostart(True, platform_name="darwin", base_dir=mac_dir) is True
    assert is_autostart_enabled(platform_name="darwin", base_dir=mac_dir) is True

    plist_file = get_macos_plist_path(mac_dir)
    payload = plistlib.loads(plist_file.read_bytes())
    assert payload["RunAtLoad"] is True
    assert "--minimized" in payload["ProgramArguments"]

    assert set_autostart(False, platform_name="darwin", base_dir=mac_dir) is True
    assert is_autostart_enabled(platform_name="darwin", base_dir=mac_dir) is False

    linux_dir = tmp_path / "autostart"
    assert is_autostart_enabled(platform_name="linux", base_dir=linux_dir) is False
    assert set_autostart(True, platform_name="linux", base_dir=linux_dir) is True
    assert is_autostart_enabled(platform_name="linux", base_dir=linux_dir) is True

    desktop_file = get_linux_desktop_path(linux_dir)
    content = desktop_file.read_text(encoding="utf-8")
    assert "Name=LocalDictate" in content
    assert "--minimized" in content
    assert "X-GNOME-Autostart-enabled=true" in content

    assert set_autostart(False, platform_name="linux", base_dir=linux_dir) is True
    assert not desktop_file.exists()


# ═══════════════════════════════════════════════════════════════════════════
# 5. HARDWARE DETECTION & RUNTIME TUNING
# ═══════════════════════════════════════════════════════════════════════════


def test_hardware_classification_tuning_and_paths():
    assert normalize_arch("AMD64") == "x86_64"
    assert normalize_arch("aarch64") == "arm64"
    assert normalize_arch("i686") == "x86"

    assert classify_hardware_tier(10, 8, ("neon", "dotprod"), "arm64") == PROFILE_PERFORMANCE
    assert classify_hardware_tier(4, 4, ("avx2",), "x86_64") == PROFILE_BALANCED
    assert classify_hardware_tier(2, 2, ("sse4_2",), "x86_64") == PROFILE_ECO
    assert classify_hardware_tier(4, 4, ("sse2",), "x86_64") == PROFILE_ECO

    cands = select_compute_type_candidates(("float32", "int8"), preferred="int8")
    assert cands[0] == "int8"
    assert "float32" in cands and "default" in cands

    hw = HardwareProfile(
        os_name="Darwin",
        os_version="24.0",
        windows_build=0,
        arch="arm64",
        cpu_name="Apple M1 Pro",
        logical_cores=10,
        physical_cores=10,
        isa_features=("dotprod", "neon"),
        supported_ct2_types=("int8", "float32"),
        recommended_tier=PROFILE_PERFORMANCE,
    )
    t_auto = compute_runtime_tuning(hw, requested_profile=PROFILE_AUTO)
    assert t_auto.effective_profile == PROFILE_PERFORMANCE
    assert t_auto.whisper_threads == 8

    t_eco = compute_runtime_tuning(hw, requested_profile=PROFILE_ECO)
    assert t_eco.whisper_threads == 2
    assert t_eco.beam_size == 2

    assert "Performance" in format_hardware_summary(hw, t_auto, lang="en")
    assert "Yüksek Performans" in format_hardware_summary(hw, t_auto, lang="tr")

    assert get_os_data_dir("darwin").as_posix().endswith("Library/Application Support/LocalDictate")
    assert get_os_data_dir("win32").name == "LocalDictate"
    assert get_os_data_dir("linux").name == "localdictate"


# ═══════════════════════════════════════════════════════════════════════════
# 6. AUTO-UPDATER (SEMVER, ASSET SELECTION, SHA-256)
# ═══════════════════════════════════════════════════════════════════════════


def test_updater_semver_assets_and_sha256(tmp_path: Path):
    assert parse_semver("v1.2.3") == (1, 2, 3, 1)
    assert parse_semver("1.2.3-beta.1") == (1, 2, 3, 0)
    assert is_newer_version("1.0.1", "1.0.0") is True
    assert is_newer_version("1.0.0", "1.0.0-rc.1") is True
    assert is_newer_version("v1.0.0", "1.0.0") is False
    assert is_newer_version("0.9.9", "1.0.0") is False

    assets = [
        {"name": "LocalDictate-Portable-v1.1.0-Windows-x64.zip", "browser_download_url": "https://x/win.zip", "size": 100},
        {"name": "LocalDictate-Setup-v1.1.0-Windows-x64.exe", "browser_download_url": "https://x/win.exe", "size": 120},
        {"name": "LocalDictate-v1.1.0-macOS-arm64.dmg", "browser_download_url": "https://x/mac.dmg", "size": 130},
        {"name": "LocalDictate-v1.1.0-Linux-x86_64.tar.gz", "browser_download_url": "https://x/lin.tar.gz", "size": 110},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt", "size": 1},
    ]

    w_name, w_url, _, w_cs = select_platform_asset(assets, platform_name="win32", machine="AMD64")
    assert w_name.endswith("Windows-x64.exe")
    assert w_url == "https://x/win.exe"
    assert w_cs.endswith("SHA256SUMS.txt")

    m_name, _, _, _ = select_platform_asset(assets, platform_name="darwin", machine="arm64")
    assert m_name.endswith("macOS-arm64.dmg")

    l_name, _, _, _ = select_platform_asset(assets, platform_name="linux", machine="x86_64")
    assert l_name.endswith("Linux-x86_64.tar.gz")

    sample = tmp_path / "payload.bin"
    sample.write_bytes(b"localdictate-v1.0.0-verified")
    digest = compute_file_sha256(str(sample))
    sums = f"{digest}  payload.bin\n"
    assert parse_sha256sums(sums, "payload.bin") == digest
    assert verify_file_sha256(str(sample), digest) is True
    assert verify_file_sha256(str(sample), "0" * 64) is False

    with patch("localdictate.updater.urllib.request.urlopen", side_effect=OSError("offline")):
        info = check_for_updates(current_version="1.0.0")
        assert info.is_update_available is False
        assert info.error is not None


# ═══════════════════════════════════════════════════════════════════════════
# 7. I18N (EN / TR PARITY & FALLBACKS)
# ═══════════════════════════════════════════════════════════════════════════


def test_i18n_en_tr_parity_and_formatting():
    assert set(TRANSLATIONS["en"].keys()) == set(TRANSLATIONS["tr"].keys())

    mgr = LanguageManager("en")
    assert mgr.t("nav_studio") == "Studio"
    assert "0.4s" in mgr.t("status_pasted", sec=0.4, suffix="")

    mgr.set_language("tr")
    assert mgr.lang == "tr"
    assert mgr.t("nav_studio") == "Stüdyo"
    assert "Yapıştırıldı" in mgr.t("status_pasted", sec=0.4, suffix="")

    # Invalid language stays safe; missing key returns key
    assert tr("unknown_key_xyz", lang="zz") == "unknown_key_xyz"


# ═══════════════════════════════════════════════════════════════════════════
# 8. SNIPPETS, VOICE COMMANDS, REGEX METACHARS, OFFLINE LOCK & TR HISTORY
# ═══════════════════════════════════════════════════════════════════════════


def test_snippets_templates_voice_commands_and_regex_metacharacters():
    fixed_now = datetime(2026, 11, 24, 14, 35)

    expanded = expand_snippet_templates(
        "Date={{date}} ISO={{iso_date}} Time={{time}} Clip={{clipboard}} Keep={{unknown_var}}",
        clipboard_getter=lambda: "https://localdictate.andacbasaran.com",
        now=fixed_now,
    )
    assert "Date=2026-11-24" in expanded
    assert "ISO=2026-11-24" in expanded
    assert "Time=14:35" in expanded
    assert "Clip=https://localdictate.andacbasaran.com" in expanded
    assert "Keep={{unknown_var}}" in expanded

    # Voice commands (EN + TR)
    en_cmd = apply_voice_commands("hey team comma new line how are you question mark")
    assert en_cmd == "hey team,\nhow are you?"

    tr_cmd = apply_voice_commands("merhaba dünya virgül yeni paragraf harika ünlem")
    assert tr_cmd == "merhaba dünya,\n\nharika!"

    # Regex metacharacters (C++, node.js, .env, C#) & Windows backslashes in destination
    rules = {
        "c++": "C++",
        "node.js": "Node.js",
        ".env": "`.env`",
        "c#": "C#",
        "docs path": r"C:\Users\andac\notes\1",
        "today": "{{date}}",
    }
    text = "we use c++, node.js, c# and .env on today at docs path."
    out = apply_replacements(text, rules, now=fixed_now)
    assert "C++," in out
    assert "Node.js," in out
    assert "C#" in out
    assert "`.env`" in out
    assert "2026-11-24" in out
    assert r"C:\Users\andac\notes\1" in out

    # Boundary safety: 'c' must not replace inside 'code'
    assert build_safe_term_pattern("c").sub("X", "code") == "code"

    # Starter pack merge preserves existing user overrides
    merged = merge_starter_pack({"lgtm": "Custom LGTM!"}, "developer")
    assert merged["lgtm"] == "Custom LGTM!"
    assert "pr checklist" in merged


def test_offline_lock_blocks_remote_llm_and_allows_localhost():
    assert is_localhost_url("http://localhost:11434") is True
    assert is_localhost_url("http://127.0.0.1:1234/v1") is True
    assert is_localhost_url("https://api.openai.com/v1") is False

    with pytest.raises(OfflineLockError):
        fetch_llm_models(
            backend="openai_compat",
            base_url="https://api.openai.com/v1",
            offline_only=True,
        )


def test_history_turkish_diacritic_search_pinning_and_exports(tmp_path: Path):
    assert normalize_search_text("İstanbul Çalışıyor ŞĞÜÖÇ") == "istanbul calisiyor sguoc"

    store = HistoryStore(db_path=tmp_path / "tr_hist.db")
    id1 = store.add(
        raw_text="istanbul calisiyor",
        final_text="İstanbul çok hızlı çalışıyor.",
        language="tr",
        model_size="small",
        audio_duration_sec=2.0,
        inference_sec=0.3,
        target_app="VS Code",
        mode="code",
        pinned=False,
    )
    id2 = store.add(
        raw_text="pinned note",
        final_text="Pinned architectural note.",
        language="en",
        model_size="small",
        audio_duration_sec=1.5,
        inference_sec=0.2,
        target_app="Notion",
        mode="bullet_notes",
        pinned=True,
    )

    # Turkish accent-insensitive search
    matches = store.list_recent(query="calisiyor")
    assert [m.id for m in matches] == [id1]
    assert [m.id for m in store.list_recent(query="istanbul")] == [id1]

    # Pinned entries appear first
    all_entries = store.list_recent()
    assert all_entries[0].id == id2

    for fmt in ("md", "csv", "txt", "json"):
        dest = tmp_path / f"export.{fmt}"
        store.export_entries(dest, fmt=fmt)
        assert dest.exists() and dest.stat().st_size > 10

    store.close()


def test_transcriber_cache_ignores_mlx_and_incomplete_snapshots(tmp_path: Path):
    from localdictate.transcriber import is_model_cached, list_cached_models

    # MLX model folder must NEVER false-positive as faster-whisper
    mlx_snap = tmp_path / "models--mlx-community--whisper-large-v3-turbo" / "snapshots" / "abc123"
    mlx_snap.mkdir(parents=True)
    (mlx_snap / "weights.safetensors").write_bytes(b"mlx")
    assert is_model_cached("large-v3-turbo", cache_dir=tmp_path) is False

    # Incomplete faster-whisper snapshot without model.bin must also return False
    fw_snap = tmp_path / "models--Systran--faster-whisper-small" / "snapshots" / "rev1"
    fw_snap.mkdir(parents=True)
    (fw_snap / "config.json").write_text("{}", encoding="utf-8")
    assert is_model_cached("small", cache_dir=tmp_path) is False

    # Complete faster-whisper snapshot with model.bin returns True
    (fw_snap / "model.bin").write_bytes(b"ct2")
    assert is_model_cached("small", cache_dir=tmp_path) is True
    assert list_cached_models(cache_dir=tmp_path) == ["small"]


def test_audio_resample_and_energy_vad():
    import numpy as np

    from localdictate.audio import detect_speech_segments, resample_audio

    sr_in = 48_000
    t = np.linspace(0.0, 1.0, sr_in, endpoint=False, dtype=np.float32)
    wave_48k = (0.15 * np.sin(2.0 * np.pi * 300.0 * t)).astype(np.float32)
    wave_48k[: sr_in // 4] = 0.0
    wave_48k[-sr_in // 4 :] = 0.0

    wave_16k = resample_audio(wave_48k, sr_in, 16_000)
    assert wave_16k.dtype == np.float32
    assert abs(wave_16k.size - 16_000) <= 4

    trimmed, ratio = detect_speech_segments(wave_16k, 16_000)
    assert 0.35 < ratio < 0.65
    assert trimmed.size < wave_16k.size

