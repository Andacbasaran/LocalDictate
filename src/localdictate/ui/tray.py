"""Cross-platform system tray icon and context menu for LocalDictate Studio 2.0."""

from __future__ import annotations

import sys

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..controller import AppState
from ..hotkeys import format_hotkey_display
from ..i18n import LanguageManager
from .widgets import create_app_pixmap


def create_tray_icon(accent: QColor) -> QIcon:
    """Render a crisp 64x64 HiDPI LocalDictate tray icon with a state-colored status indicator."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        base = create_app_pixmap(28)
        painter.drawPixmap(QRectF(4, 4, size - 8, size - 8), base, QRectF(base.rect()))

        # State accent ring + bottom-right status beacon
        painter.setPen(QPen(accent, 3.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(3, 3, size - 6, size - 6), 14.0, 14.0)

        painter.setPen(QPen(QColor("#0A0A0C"), 2.5))
        painter.setBrush(accent)
        painter.drawEllipse(QRectF(size - 20, size - 20, 16, 16))
    finally:
        painter.end()
    return QIcon(pixmap)


class TrayManager(QSystemTrayIcon):
    """Manages the cross-platform system tray icon and Studio context menu."""

    open_studio_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    history_requested = pyqtSignal()
    copy_last_requested = pyqtSignal()
    toggle_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(
        self,
        active_hotkey: str,
        i18n: LanguageManager | None = None,
        parent=None,
    ) -> None:
        self._i18n = i18n or LanguageManager("en")
        self._icons = {
            AppState.IDLE.value: create_tray_icon(QColor("#10B981")),
            AppState.RECORDING.value: create_tray_icon(QColor("#E11D48")),
            AppState.TRANSCRIBING.value: create_tray_icon(QColor("#8B5CF6")),
            AppState.REFINING.value: create_tray_icon(QColor("#A78BFA")),
            AppState.LOADING_MODEL.value: create_tray_icon(QColor("#F59E0B")),
            AppState.ERROR.value: create_tray_icon(QColor("#FB7185")),
        }
        super().__init__(self._icons[AppState.IDLE.value], parent)
        self._active_hotkey = active_hotkey
        self._last_status_msg = self._i18n.t("status_ready")

        self._menu = QMenu()
        self._status_action = QAction("", self._menu)
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)

        self._hotkey_action = QAction("", self._menu)
        self._hotkey_action.setEnabled(False)
        self._menu.addAction(self._hotkey_action)

        self._menu.addSeparator()

        self._open_studio_action = QAction("", self._menu)
        self._open_studio_action.triggered.connect(self.open_studio_requested.emit)
        self._menu.addAction(self._open_studio_action)

        self._toggle_action = QAction("", self._menu)
        self._toggle_action.triggered.connect(self.toggle_requested.emit)
        self._menu.addAction(self._toggle_action)

        self._copy_last_action = QAction("", self._menu)
        self._copy_last_action.setEnabled(False)
        self._copy_last_action.triggered.connect(self.copy_last_requested.emit)
        self._menu.addAction(self._copy_last_action)

        self._menu.addSeparator()

        self._history_action = QAction("", self._menu)
        self._history_action.triggered.connect(self.history_requested.emit)
        self._menu.addAction(self._history_action)

        self._settings_action = QAction("", self._menu)
        self._settings_action.triggered.connect(self.settings_requested.emit)
        self._menu.addAction(self._settings_action)

        self._menu.addSeparator()

        self._quit_action = QAction("", self._menu)
        self._quit_action.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)
        self.retranslate(self._i18n)
        self.activated.connect(self._on_activated)

    def retranslate(self, i18n: LanguageManager) -> None:
        self._i18n = i18n
        disp_hk = format_hotkey_display(self._active_hotkey)
        self._status_action.setText(f"Status: {self._last_status_msg}")
        self._hotkey_action.setText(f"Hotkey: {disp_hk}")
        self._open_studio_action.setText(i18n.t("tray_open_studio"))
        self._toggle_action.setText(i18n.t("tray_toggle"))
        self._copy_last_action.setText(i18n.t("tray_copy_last"))
        self._history_action.setText(i18n.t("tray_history"))
        self._settings_action.setText(i18n.t("tray_settings"))
        self._quit_action.setText(i18n.t("tray_quit"))
        self.setToolTip(f"LocalDictate — {disp_hk}")

    def update_hotkey_label(self, active_hotkey: str) -> None:
        self._active_hotkey = active_hotkey
        disp_hk = format_hotkey_display(active_hotkey)
        self._hotkey_action.setText(f"Hotkey: {disp_hk}")
        self.setToolTip(f"LocalDictate — {disp_hk}")

    def enable_copy_last(self, enabled: bool = True) -> None:
        self._copy_last_action.setEnabled(enabled)

    def on_state_changed(self, state: str, message: str) -> None:
        icon = self._icons.get(state, self._icons[AppState.IDLE.value])
        self.setIcon(icon)
        self._last_status_msg = message
        disp_hk = format_hotkey_display(self._active_hotkey)
        self._status_action.setText(f"Status: {message}")
        self.setToolTip(f"LocalDictate ({message}) — {disp_hk}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # On macOS left-click shows the menu bar dropdown naturally; on Win/Linux trigger opens Studio
        if sys.platform == "darwin":
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self.open_studio_requested.emit()
            return
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_studio_requested.emit()
