"""Tabbed settings dialog for hotkeys, Whisper model, Ollama AI, and personal dictionary."""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt
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
    HOTKEY_MODES,
    OLLAMA_STYLES,
    AppConfig,
)
from ..postprocess import fetch_ollama_models


DIALOG_STYLESHEET = """
QDialog {
    background-color: #12151e;
    color: #e2e8f0;
    font-family: "Segoe UI";
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #273043;
    border-radius: 8px;
    background-color: #161a25;
    padding: 10px;
}
QTabBar::tab {
    background-color: #1b202e;
    color: #94a3b8;
    border: 1px solid #273043;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 14px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background-color: #242b3d;
    color: #f8fafc;
    font-weight: 600;
}
QLabel {
    color: #cbd5e1;
}
QComboBox, QLineEdit, QSpinBox, QPlainTextEdit {
    background-color: #1e2433;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus {
    border-color: #6366f1;
}
QPushButton {
    background-color: #252d3f;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
}
QPushButton:hover {
    background-color: #334155;
}
QCheckBox {
    color: #e2e8f0;
    spacing: 8px;
}
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


class SettingsDialog(QDialog):
    """Tabbed modal dialog for editing LocalDictate preferences."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("LocalDictate — Ayarlar")
        self.setMinimumWidth(540)
        self.setStyleSheet(DIALOG_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel("LocalDictate Ayarları")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #f8fafc;")
        layout.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "Genel & Kısayol")
        tabs.addTab(self._build_model_tab(), "Model & Ses")
        tabs.addTab(self._build_ai_dictionary_tab(), "AI (Ollama) & Sözlük")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
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
        form.addRow("Kısayol Modu:", self._mode_combo)

        self._toggle_edit = QLineEdit(self._config.toggle_hotkey)
        self._toggle_edit.setPlaceholderText("ör. ctrl+alt+space veya alt+space")
        form.addRow("Aç-Kapa Kısayolu:", self._toggle_edit)

        self._ptt_edit = QLineEdit(self._config.ptt_hotkey)
        self._ptt_edit.setPlaceholderText("ör. ctrl_r veya f9")
        form.addRow("Bas-Konuş Tuşu:", self._ptt_edit)

        presets_row = QHBoxLayout()
        for label, mode, hk in [
            ("Ctrl+Alt+Space", "toggle", "ctrl+alt+space"),
            ("Sağ Ctrl (PTT)", "push_to_talk", "ctrl_r"),
            ("F9 (PTT)", "push_to_talk", "f9"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _c=False, m=mode, k=hk: self._apply_preset(m, k))
            presets_row.addWidget(btn)
        form.addRow("Hızlı Ön Ayarlar:", presets_row)

        self._pos_combo = QComboBox()
        self._pos_combo.addItem("Alt Orta", "bottom_center")
        self._pos_combo.addItem("Üst Orta", "top_center")
        self._select_by_data(self._pos_combo, self._config.overlay_position)
        form.addRow("Gösterge Konumu:", self._pos_combo)

        self._sounds_check = QCheckBox("Başlangıç / bitiş ses efektlerini çal")
        self._sounds_check.setChecked(self._config.sound_effects)
        form.addRow("", self._sounds_check)

        self._restore_clip_check = QCheckBox("Yapıştırma sonrası önceki panoyu geri yükle")
        self._restore_clip_check.setChecked(self._config.restore_clipboard)
        form.addRow("", self._restore_clip_check)

        self._trailing_space_check = QCheckBox("Yapıştırılan metnin sonuna otomatik boşluk ekle")
        self._trailing_space_check.setChecked(self._config.append_trailing_space)
        form.addRow("", self._trailing_space_check)

        self._history_check = QCheckBox("Dikte geçmişini ve istatistikleri yerel olarak kaydet")
        self._history_check.setChecked(self._config.save_history)
        form.addRow("", self._history_check)

        self._startup_check = QCheckBox("Windows açılışında otomatik başlat")
        self._startup_check.setChecked(self._config.launch_at_startup)
        form.addRow("", self._startup_check)

        hint = QLabel("İpucu: Kayıt sırasında Esc tuşuna basarak kaydı iptal edebilirsiniz.")
        hint.setStyleSheet("font-size: 11px; color: #94a3b8;")
        form.addRow("", hint)
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
        form.addRow("Whisper Modeli:", self._model_combo)

        self._lang_combo = QComboBox()
        for value, label in AVAILABLE_LANGUAGES:
            self._lang_combo.addItem(label, value)
        self._select_by_data(self._lang_combo, self._config.language)
        form.addRow("Dil:", self._lang_combo)

        self._mic_combo = QComboBox()
        self._mic_combo.addItem("Sistem Varsayılanı", None)
        for dev_idx, dev_name in list_input_devices():
            self._mic_combo.addItem(dev_name, dev_idx)
        self._select_by_data(self._mic_combo, self._config.input_device)
        form.addRow("Mikrofon:", self._mic_combo)

        self._beam_spin = QSpinBox()
        self._beam_spin.setRange(1, 10)
        self._beam_spin.setValue(self._config.beam_size)
        form.addRow("Beam Size (Doğruluk/Hız):", self._beam_spin)

        self._threads_spin = QSpinBox()
        self._threads_spin.setRange(0, 32)
        self._threads_spin.setSpecialValueText("Otomatik")
        self._threads_spin.setValue(self._config.cpu_threads)
        form.addRow("CPU İş Parçacığı:", self._threads_spin)

        self._vad_check = QCheckBox("Silero VAD sessizlik filtresini kullan (önerilen)")
        self._vad_check.setChecked(self._config.vad_filter)
        form.addRow("", self._vad_check)

        return page

    def _build_ai_dictionary_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self._ollama_check = QCheckBox("Lokal Ollama LLM ile noktalama ve metin temizleme")
        self._ollama_check.setChecked(self._config.ollama_enabled)
        form.addRow("", self._ollama_check)

        self._ollama_url_edit = QLineEdit(self._config.ollama_url)
        self._ollama_url_edit.setPlaceholderText("http://localhost:11434")
        form.addRow("Ollama Adresi:", self._ollama_url_edit)

        model_row = QHBoxLayout()
        self._ollama_model_combo = QComboBox()
        self._ollama_model_combo.setEditable(True)
        self._ollama_model_combo.setCurrentText(self._config.ollama_model)
        model_row.addWidget(self._ollama_model_combo, stretch=1)

        refresh_btn = QPushButton("Bağlantıyı Test Et")
        refresh_btn.clicked.connect(self._test_ollama)
        model_row.addWidget(refresh_btn)
        form.addRow("Ollama Modeli:", model_row)

        self._ollama_status = QLabel("")
        self._ollama_status.setStyleSheet("font-size: 11px; color: #94a3b8;")
        form.addRow("", self._ollama_status)

        self._ollama_style_combo = QComboBox()
        for value, label in OLLAMA_STYLES:
            self._ollama_style_combo.addItem(label, value)
        self._select_by_data(self._ollama_style_combo, self._config.ollama_style)
        form.addRow("Düzenleme Stili:", self._ollama_style_combo)

        self._vocab_edit = QLineEdit(", ".join(self._config.custom_vocabulary))
        self._vocab_edit.setPlaceholderText("ör. LocalDictate, PyQt6, FastAPI, Kubernetes")
        form.addRow("Özel Kelimeler:", self._vocab_edit)

        self._replacements_edit = QPlainTextEdit(_format_replacements(self._config.replacements))
        self._replacements_edit.setPlaceholderText("Her satıra bir kural:\nvisper -> Wispr\nimzam -> Saygılarımla, Andaç")
        self._replacements_edit.setFixedHeight(86)
        form.addRow("Otomatik Değiştirme:", self._replacements_edit)

        return page

    def _test_ollama(self) -> None:
        url = self._ollama_url_edit.text().strip() or "http://localhost:11434"
        try:
            models = fetch_ollama_models(url, timeout=3.0)
        except Exception as exc:
            self._ollama_status.setStyleSheet("font-size: 11px; color: #f87171;")
            self._ollama_status.setText(f"Bağlanılamadı: {exc}")
            return

        current = self._ollama_model_combo.currentText().strip()
        self._ollama_model_combo.clear()
        for m in models:
            self._ollama_model_combo.addItem(m)
        if current:
            self._ollama_model_combo.setCurrentText(current)

        self._ollama_status.setStyleSheet("font-size: 11px; color: #34d399;")
        self._ollama_status.setText(f"Bağlandı — {len(models)} model bulundu.")

    def _apply_preset(self, mode: str, hotkey: str) -> None:
        self._select_by_data(self._mode_combo, mode)
        if mode == "push_to_talk":
            self._ptt_edit.setText(hotkey)
        else:
            self._toggle_edit.setText(hotkey)

    @staticmethod
    def _select_by_data(combo: QComboBox, value) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def build_config(self) -> AppConfig:
        """Return an updated AppConfig based on current form values."""
        toggle_hk = self._toggle_edit.text().strip() or self._config.toggle_hotkey
        ptt_hk = self._ptt_edit.text().strip() or self._config.ptt_hotkey
        vocab = [w.strip() for w in self._vocab_edit.text().split(",") if w.strip()]
        replacements = _parse_replacements(self._replacements_edit.toPlainText())

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
            ollama_style=str(self._ollama_style_combo.currentData()),
            custom_vocabulary=vocab,
            replacements=replacements,
        )
