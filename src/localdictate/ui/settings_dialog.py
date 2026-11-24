"""Standalone tabbed settings dialog (Studio 2.0 palette, async LLM test, backwards-compatible)."""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..audio import list_input_devices
from ..config import (
    AVAILABLE_LANGUAGES,
    AVAILABLE_MODELS,
    DICTATION_MODES,
    HOTKEY_MODES,
    AppConfig,
)
from ..hardware import get_ui_font_family
from ..postprocess import fetch_llm_models


def _build_dialog_stylesheet() -> str:
    font = get_ui_font_family()
    return f"""
QDialog {{
    background-color: #0A0A0C;
    color: #FAFAFA;
    font-family: '{font}', 'Segoe UI', sans-serif;
    font-size: 13px;
}}
QTabWidget::pane {{
    border: 1px solid #24242A;
    border-radius: 8px;
    background-color: #141417;
    padding: 10px;
}}
QTabBar::tab {{
    background-color: #111113;
    color: #A1A1AA;
    border: 1px solid #24242A;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 14px;
    margin-right: 4px;
}}
QTabBar::tab:selected {{
    background-color: #1B1B21;
    color: #FAFAFA;
    font-weight: 600;
}}
QComboBox, QLineEdit, QSpinBox, QPlainTextEdit {{
    background-color: #0F0F13;
    color: #FAFAFA;
    border: 1px solid #26262E;
    border-radius: 6px;
    padding: 6px 10px;
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border-color: #8B5CF6;
}}
QPushButton {{
    background-color: #1B1B21;
    color: #FAFAFA;
    border: 1px solid #2B2B34;
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background-color: #23232B;
}}
"""


def _format_replacements(replacements: dict[str, str]) -> str:
    return "\n".join(f"{k} -> {v}" for k, v in replacements.items())


def _parse_replacements(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "->" not in line:
            continue
        src, dst = line.split("->", 1)
        src = src.strip()
        dst = dst.strip()
        if src:
            parsed[src] = dst
    return parsed


class _AsyncOllamaProbe(QThread):
    done = pyqtSignal(list, str)

    def __init__(self, backend: str, url: str, offline_only: bool, parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._url = url
        self._offline_only = offline_only

    def run(self) -> None:
        try:
            models = fetch_llm_models(
                backend=self._backend,
                base_url=self._url,
                offline_only=self._offline_only,
                timeout=3.0,
            )
            self.done.emit(models, "")
        except Exception as exc:
            self.done.emit([], str(exc))


class SettingsDialog(QDialog):
    """Tabbed modal dialog for editing LocalDictate preferences (non-blocking LLM test)."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._probe_thread: _AsyncOllamaProbe | None = None
        self.setWindowTitle("LocalDictate — Settings")
        self.setMinimumWidth(560)
        self.setStyleSheet(_build_dialog_stylesheet())

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel("LocalDictate Settings")
        header.setStyleSheet("font-size: 16px; font-weight: 700; color: #FAFAFA;")
        layout.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "General & Hotkeys")
        tabs.addTab(self._build_model_tab(), "Model & Audio")
        tabs.addTab(self._build_ai_dictionary_tab(), "LLM & Dictionary")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self._mode_combo = QComboBox()
        for value, label in HOTKEY_MODES:
            self._mode_combo.addItem(label, value)
        self._select_by_data(self._mode_combo, self._config.hotkey_mode)
        form.addRow("Trigger Mode:", self._mode_combo)

        self._toggle_edit = QLineEdit(self._config.toggle_hotkey)
        form.addRow("Toggle Hotkey:", self._toggle_edit)

        self._ptt_edit = QLineEdit(self._config.ptt_hotkey)
        form.addRow("Push-to-Talk Key:", self._ptt_edit)

        self._pos_combo = QComboBox()
        self._pos_combo.addItem("Bottom Center", "bottom_center")
        self._pos_combo.addItem("Top Center", "top_center")
        self._select_by_data(self._pos_combo, self._config.overlay_position)
        form.addRow("HUD Position:", self._pos_combo)

        self._sounds_check = QCheckBox("Play subtle start / stop audio cues")
        self._sounds_check.setChecked(self._config.sound_effects)
        form.addRow("", self._sounds_check)

        self._restore_clip_check = QCheckBox("Restore previous clipboard after paste")
        self._restore_clip_check.setChecked(self._config.restore_clipboard)
        form.addRow("", self._restore_clip_check)

        self._trailing_space_check = QCheckBox("Append trailing space after pasted text")
        self._trailing_space_check.setChecked(self._config.append_trailing_space)
        form.addRow("", self._trailing_space_check)

        self._history_check = QCheckBox("Save local SQLite dictation history")
        self._history_check.setChecked(self._config.save_history)
        form.addRow("", self._history_check)

        self._startup_check = QCheckBox("Launch automatically at OS login")
        self._startup_check.setChecked(self._config.launch_at_startup)
        form.addRow("", self._startup_check)
        return page

    def _build_model_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self._model_combo = QComboBox()
        for value, label in AVAILABLE_MODELS:
            self._model_combo.addItem(label, value)
        self._select_by_data(self._model_combo, self._config.model_size)
        form.addRow("Whisper Model:", self._model_combo)

        self._lang_combo = QComboBox()
        for value, label in AVAILABLE_LANGUAGES:
            self._lang_combo.addItem(label, value)
        self._select_by_data(self._lang_combo, self._config.language)
        form.addRow("Language:", self._lang_combo)

        self._mic_combo = QComboBox()
        self._mic_combo.addItem("System Default", None)
        for dev_idx, dev_name in list_input_devices():
            self._mic_combo.addItem(dev_name, dev_idx)
        self._select_by_data(self._mic_combo, self._config.input_device)
        form.addRow("Microphone:", self._mic_combo)

        self._beam_spin = QSpinBox()
        self._beam_spin.setRange(1, 10)
        self._beam_spin.setValue(self._config.beam_size)
        form.addRow("Beam Size:", self._beam_spin)

        self._threads_spin = QSpinBox()
        self._threads_spin.setRange(0, 32)
        self._threads_spin.setSpecialValueText("Auto")
        self._threads_spin.setValue(self._config.cpu_threads)
        form.addRow("CPU Threads:", self._threads_spin)

        self._vad_check = QCheckBox("Enable Silero VAD silence filter")
        self._vad_check.setChecked(self._config.vad_filter)
        form.addRow("", self._vad_check)
        return page

    def _build_ai_dictionary_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self._ollama_check = QCheckBox("Enable local LLM refinement")
        self._ollama_check.setChecked(self._config.ollama_enabled)
        form.addRow("", self._ollama_check)

        self._ollama_url_edit = QLineEdit(self._config.ollama_url)
        form.addRow("LLM Endpoint:", self._ollama_url_edit)

        model_row = QHBoxLayout()
        self._ollama_model_combo = QComboBox()
        self._ollama_model_combo.setEditable(True)
        self._ollama_model_combo.setCurrentText(self._config.ollama_model)
        model_row.addWidget(self._ollama_model_combo, stretch=1)

        self._refresh_btn = QPushButton("Test Connection")
        self._refresh_btn.clicked.connect(self._test_ollama_async)
        model_row.addWidget(self._refresh_btn)
        form.addRow("LLM Model:", model_row)

        self._ollama_status = QLabel("")
        self._ollama_status.setStyleSheet("font-size: 11px; color: #71717A;")
        form.addRow("", self._ollama_status)

        self._ollama_style_combo = QComboBox()
        for value, label in DICTATION_MODES:
            self._ollama_style_combo.addItem(label, value)
        self._select_by_data(self._ollama_style_combo, self._config.effective_style)
        form.addRow("Dictation Mode:", self._ollama_style_combo)

        self._vocab_edit = QLineEdit(", ".join(self._config.custom_vocabulary))
        form.addRow("Custom Vocabulary:", self._vocab_edit)

        self._replacements_edit = QPlainTextEdit(_format_replacements(self._config.replacements))
        self._replacements_edit.setFixedHeight(86)
        form.addRow("Replacements:", self._replacements_edit)
        return page

    def _test_ollama_async(self) -> None:
        if self._probe_thread is not None and self._probe_thread.isRunning():
            return
        url = self._ollama_url_edit.text().strip() or "http://localhost:11434"
        self._refresh_btn.setEnabled(False)
        self._ollama_status.setText("Connecting...")
        t = _AsyncOllamaProbe(
            backend=self._config.llm_backend,
            url=url,
            offline_only=self._config.offline_only,
            parent=self,
        )
        t.done.connect(self._on_probe_done)
        self._probe_thread = t
        t.start()

    def _on_probe_done(self, models: list, error: str) -> None:
        self._refresh_btn.setEnabled(True)
        if error:
            self._ollama_status.setStyleSheet("font-size: 11px; color: #FB7185;")
            self._ollama_status.setText(f"Failed: {error}")
            return
        current = self._ollama_model_combo.currentText().strip()
        self._ollama_model_combo.clear()
        for m in models:
            self._ollama_model_combo.addItem(m)
        if current:
            self._ollama_model_combo.setCurrentText(current)
        self._ollama_status.setStyleSheet("font-size: 11px; color: #10B981;")
        self._ollama_status.setText(f"Connected — {len(models)} model(s) found.")

    @staticmethod
    def _select_by_data(combo: QComboBox, value) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def build_config(self) -> AppConfig:
        toggle_hk = self._toggle_edit.text().strip() or self._config.toggle_hotkey
        ptt_hk = self._ptt_edit.text().strip() or self._config.ptt_hotkey
        vocab = [w.strip() for w in self._vocab_edit.text().split(",") if w.strip()]
        replacements = _parse_replacements(self._replacements_edit.toPlainText())
        mode = str(self._ollama_style_combo.currentData())

        return replace(
            self._config,
            hotkey_mode=str(self._mode_combo.currentData()),
            toggle_hotkey=toggle_hk,
            ptt_hotkey=ptt_hk,
            model_size=str(self._model_combo.currentData()),
            language=str(self._lang_combo.currentData()),
            beam_size=self._beam_spin.value(),
            cpu_threads=self._threads_spin.value(),
            input_device=self._mic_combo.currentData(),
            overlay_position=str(self._pos_combo.currentData()),
            vad_filter=self._vad_check.isChecked(),
            sound_effects=self._sounds_check.isChecked(),
            restore_clipboard=self._restore_clip_check.isChecked(),
            append_trailing_space=self._trailing_space_check.isChecked(),
            save_history=self._history_check.isChecked(),
            launch_at_startup=self._startup_check.isChecked(),
            ollama_enabled=self._ollama_check.isChecked(),
            ollama_url=self._ollama_url_edit.text().strip() or "http://localhost:11434",
            ollama_model=self._ollama_model_combo.currentText().strip() or "qwen2.5:3b",
            ollama_style=mode,
            dictation_mode=mode,
            custom_vocabulary=vocab,
            replacements=replacements,
        )
