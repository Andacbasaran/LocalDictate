"""Offscreen PyQt6 UI tests for StudioWindow, FloatingOverlay, and LiveWaveformBar."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from localdictate.config import AppConfig, load_config, save_config
from localdictate.controller import AppState, DictationController, DictationOutcome
from localdictate.history import HistoryStore
from localdictate.ui.overlay import FloatingOverlay
from localdictate.ui.studio_window import StudioWindow
from localdictate.ui.widgets import LiveWaveformBar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _build_test_studio(tmp_path: Path, monkeypatch, config: AppConfig | None = None):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(
        "localdictate.controller.save_config",
        lambda cfg, path=None: save_config(cfg, path or cfg_path),
    )
    monkeypatch.setattr("localdictate.controller.set_autostart", lambda _enabled: True)

    store = HistoryStore(db_path=tmp_path / "ui_history.db")
    store.add(
        raw_text="istanbul mimari toplantı",
        final_text="İstanbul mimari toplantısı saat 14:00'te.",
        language="tr",
        model_size="small",
        audio_duration_sec=3.0,
        inference_sec=0.28,
        used_llm=False,
        target_app="Mail",
        mode="formal",
        pinned=True,
    )
    store.add(
        raw_text="migrated worker to asyncio",
        final_text="Migrated worker to asyncio.",
        language="en",
        model_size="small",
        audio_duration_sec=2.0,
        inference_sec=0.25,
        used_llm=True,
        target_app="VS Code",
        mode="code",
        pinned=False,
    )

    cfg = config or AppConfig(
        ui_language="en",
        sound_effects=False,
        offline_only=True,
        custom_vocabulary=["LocalDictate", "PyQt6"],
        snippets={"lgtm": "Looks good to me!"},
    )

    rec = MagicMock()
    rec.is_recording = False
    rec.get_latest_level.return_value = 0.0
    trans = MagicMock()
    trans.active_compute_type = "int8"
    trans.active_threads = 4
    hk = MagicMock()
    inj = MagicMock()
    inj.inject.return_value = True

    controller = DictationController(
        config=cfg,
        recorder=rec,
        transcriber=trans,
        injector=inj,
        hotkey_manager=hk,
        history=store,
        active_app_detector=lambda: "VS Code",
    )
    win = StudioWindow(controller=controller, history=store)
    return win, controller, store, cfg_path


def test_studio_window_tabs_i18n_and_dictation_stage(qapp, tmp_path: Path, monkeypatch):
    win, _ctrl, store, _cfg_path = _build_test_studio(tmp_path, monkeypatch)
    try:
        # Tab switching 0 -> 1 -> 2 -> 0
        assert win.stack.currentIndex() == 0
        win.switch_tab(1)
        assert win.stack.currentIndex() == 1
        win.switch_tab(2)
        assert win.stack.currentIndex() == 2
        win.switch_tab(0)
        assert win.stack.currentIndex() == 0

        # Bilingual TR / EN live retranslation
        win.retranslate_ui("tr")
        assert win.i18n.lang == "tr"
        assert win.btn_nav_studio.nav_text() == "Stüdyo"
        assert win.btn_nav_history.nav_text() == "Geçmiş & Kısaltmalar"
        assert win.btn_nav_settings.nav_text() == "Ayarlar & Telemetri"

        win.retranslate_ui("en")
        assert win.btn_nav_studio.nav_text() == "Studio"
        assert win.btn_nav_history.nav_text() == "History & Snippets"

        # Dictation outcome updates stage widgets & metrics
        outcome = DictationOutcome(
            raw_text="hello team comma new line ready to ship",
            final_text="Hello team,\nReady to ship.",
            language="en",
            mode="code",
            target_app="VS Code",
            audio_duration_sec=2.5,
            stt_sec=0.31,
            llm_sec=0.0,
            paste_sec=0.015,
            used_llm=False,
            pasted=True,
            wpm=144,
        )
        win.on_dictation_completed(outcome)
        assert win.txt_raw_stage.toPlainText() == outcome.raw_text
        assert win.txt_refined_stage.toPlainText() == outcome.final_text
        assert win.lbl_wpm_pill.text() == "144 WPM"
        assert "310ms" in win._stage_chips["stt"].text()
        assert "VS Code" in win.lbl_target_badge.text()

        # Offscreen paint succeeds cleanly
        win.resize(960, 640)
        qapp.processEvents()
        pix = win.grab()
        assert not pix.isNull() and pix.width() == 960 and pix.height() == 640
    finally:
        win.request_force_quit()
        store.close()


def test_studio_history_search_and_settings_persistence(qapp, tmp_path: Path, monkeypatch):
    win, controller, store, cfg_path = _build_test_studio(tmp_path, monkeypatch)
    try:
        win.switch_tab(1)
        assert win.list_history.count() == 2

        # Turkish diacritic-insensitive search via Studio UI
        win.edit_history_search.setText("istanbul")
        win.refresh_history()
        assert win.list_history.count() == 1

        # Pinned-only filter
        win.edit_history_search.setText("")
        win.btn_pinned_filter.setChecked(True)
        win.refresh_history()
        assert win.list_history.count() == 1
        win.btn_pinned_filter.setChecked(False)

        # Install starter pack and verify persistence
        win._install_starter_pack("developer")
        assert "pr checklist" in controller.config.snippets

        # Save settings from Tab 2 and verify persisted JSON roundtrip
        emitted: list[AppConfig] = []
        win.config_applied.connect(emitted.append)

        win.switch_tab(2)
        win.edit_toggle_hk.setText("ctrl+shift+d")
        win.spin_beam.setValue(3)
        win.sw_vad.setChecked(False)
        win._select_combo_data(win.combo_ui_lang, "tr")
        win._save_settings_from_ui()

        assert len(emitted) == 1
        assert emitted[0].toggle_hotkey == "ctrl+shift+d"
        assert emitted[0].beam_size == 3
        assert emitted[0].vad_filter is False
        assert emitted[0].ui_language == "tr"
        assert win.i18n.lang == "tr"

        reloaded = load_config(cfg_path)
        assert reloaded.toggle_hotkey == "ctrl+shift+d"
        assert reloaded.beam_size == 3
        assert reloaded.vad_filter is False
        assert reloaded.ui_language == "tr"
    finally:
        win.request_force_quit()
        store.close()


def test_floating_overlay_and_live_waveform_offscreen(qapp):
    overlay = FloatingOverlay(position="bottom_center", mode="code", language="en")
    try:
        assert overlay._micro_pill_text() == "CODE · EN"
        overlay.set_context_badge("translate_en", "tr")
        assert overlay._micro_pill_text() == "TR→EN"
        overlay.set_position("top_center")

        overlay.on_state_changed(AppState.RECORDING.value, "Listening...")
        overlay.on_audio_level(0.75)
        overlay._tick()
        qapp.processEvents()
        pix = overlay.grab()
        assert not pix.isNull() and pix.width() == overlay.PILL_WIDTH

        overlay.on_state_changed(AppState.TRANSCRIBING.value, "Transcribing...")
        overlay._tick()
        overlay.on_state_changed(AppState.ERROR.value, "Mic error")
        overlay.on_state_changed(AppState.IDLE.value, "Ready")
    finally:
        overlay._anim_timer.stop()
        overlay._hide_timer.stop()
        overlay.close()

    wave = LiveWaveformBar(bar_count=24)
    try:
        wave.resize(620, 68)
        wave.set_state("recording")
        wave.push_level(0.82)
        wave.set_levels([0.2, 0.5, 0.9, 0.4, 0.7])
        wave.set_state("transcribing")
        pix_w = wave.grab()
        assert not pix_w.isNull() and pix_w.width() == 620
        wave.reset_idle()
    finally:
        wave.close()
