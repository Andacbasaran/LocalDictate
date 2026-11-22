"""Settings dialog for configuring hotkeys, Whisper model, language, and audio device."""

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
    QPushButton,
    QVBoxLayout,
)

from ..audio import list_input_devices
from ..config import (
    AVAILABLE_LANGUAGES,
    AVAILABLE_MODELS,
    HOTKEY_MODES,
    AppConfig,
)


DIALOG_STYLESHEET = """
QDialog {
    background-color: #14171f;
    color: #e2e8f0;
    font-family: "Segoe UI";
    font-size: 13px;
}
QLabel {
    color: #cbd5e1;
}
QComboBox, QLineEdit {
    background-color: #1e2330;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
}
QComboBox:focus, QLineEdit:focus {
    border-color: #6366f1;
}
QPushButton {
    background-color: #262d3d;
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


class SettingsDialog(QDialog):
    """Modal dialog for editing LocalDictate preferences."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("LocalDictate — Ayarlar")
        self.setMinimumWidth(460)
        self.setStyleSheet(DIALOG_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        header = QLabel("LocalDictate Ayarları")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #f8fafc;")
        layout.addWidget(header)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        # Hotkey mode
        self._mode_combo = QComboBox()
        for value, label in HOTKEY_MODES:
            self._mode_combo.addItem(label, value)
        self._select_by_data(self._mode_combo, config.hotkey_mode)
        form.addRow("Kısayol Modu:", self._mode_combo)

        # Toggle hotkey
        self._toggle_edit = QLineEdit(config.toggle_hotkey)
        self._toggle_edit.setPlaceholderText("ör. ctrl+alt+space veya alt+space")
        form.addRow("Aç-Kapa Kısayolu:", self._toggle_edit)

        # PTT hotkey
        self._ptt_edit = QLineEdit(config.ptt_hotkey)
        self._ptt_edit.setPlaceholderText("ör. ctrl_r veya f9")
        form.addRow("Bas-Konuş Tuşu:", self._ptt_edit)

        # Quick presets row
        presets_row = QHBoxLayout()
        for label, mode, hk in [
            ("Ctrl+Alt+Space", "toggle", "ctrl+alt+space"),
            ("Sağ Ctrl (PTT)", "push_to_talk", "ctrl_r"),
            ("F9 (PTT)", "push_to_talk", "f9"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, m=mode, k=hk: self._apply_preset(m, k))
            presets_row.addWidget(btn)
        form.addRow("Hızlı Ön Ayarlar:", presets_row)

        # Whisper model
        self._model_combo = QComboBox()
        for value, label in AVAILABLE_MODELS:
            self._model_combo.addItem(label, value)
        self._select_by_data(self._model_combo, config.model_size)
        form.addRow("Whisper Modeli:", self._model_combo)

        # Language
        self._lang_combo = QComboBox()
        for value, label in AVAILABLE_LANGUAGES:
            self._lang_combo.addItem(label, value)
        self._select_by_data(self._lang_combo, config.language)
        form.addRow("Dil:", self._lang_combo)

        # Microphone device
        self._mic_combo = QComboBox()
        self._mic_combo.addItem("Sistem Varsayılanı", None)
        for dev_idx, dev_name in list_input_devices():
            self._mic_combo.addItem(dev_name, dev_idx)
        self._select_by_data(self._mic_combo, config.input_device)
        form.addRow("Mikrofon:", self._mic_combo)

        # Overlay position
        self._pos_combo = QComboBox()
        self._pos_combo.addItem("Alt Orta", "bottom_center")
        self._pos_combo.addItem("Üst Orta", "top_center")
        self._select_by_data(self._pos_combo, config.overlay_position)
        form.addRow("Gösterge Konumu:", self._pos_combo)

        # Checkboxes
        self._vad_check = QCheckBox("Silero VAD sessizlik filtresini kullan (önerilen)")
        self._vad_check.setChecked(config.vad_filter)
        form.addRow("", self._vad_check)

        self._restore_clip_check = QCheckBox("Yapıştırma sonrası önceki panoyu geri yükle")
        self._restore_clip_check.setChecked(config.restore_clipboard)
        form.addRow("", self._restore_clip_check)

        layout.addLayout(form)

        hint = QLabel("İpucu: Kayıt sırasında Esc tuşuna basarak kaydı iptal edebilirsiniz.")
        hint.setStyleSheet("font-size: 11px; color: #94a3b8;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        return replace(
            self._config,
            hotkey_mode=str(self._mode_combo.currentData()),
            toggle_hotkey=toggle_hk,
            ptt_hotkey=ptt_hk,
            model_size=str(self._model_combo.currentData()),
            language=str(self._lang_combo.currentData()),
            input_device=self._mic_combo.currentData(),
            overlay_position=str(self._pos_combo.currentData()),
            vad_filter=self._vad_check.isChecked(),
            restore_clipboard=self._restore_clip_check.isChecked(),
        )
