"""System tray icon and menu for LocalDictate."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..controller import AppState


def create_tray_icon(accent: QColor) -> QIcon:
    """Render a crisp 64x64 microphone system tray icon with a state-colored badge."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Dark rounded background circle
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(24, 27, 36))
    painter.drawEllipse(QRectF(2, 2, size - 4, size - 4))

    # Colored ring
    painter.setPen(QPen(accent, 4.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(4, 4, size - 8, size - 8))

    # Microphone capsule
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(248, 250, 252))
    painter.drawRoundedRect(QRectF(24, 14, 16, 24), 8.0, 8.0)

    # Microphone arc & stand
    pen = QPen(QColor(248, 250, 252), 3.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawArc(QRectF(17, 20, 30, 24), 180 * 16, 180 * 16)
    painter.drawLine(32, 44, 32, 51)
    painter.drawLine(24, 51, 40, 51)

    painter.end()
    return QIcon(pixmap)


class TrayManager(QSystemTrayIcon):
    """Manages the Windows system tray icon and context menu."""

    settings_requested = pyqtSignal()
    toggle_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, active_hotkey: str, parent=None) -> None:
        self._icons = {
            AppState.IDLE.value: create_tray_icon(QColor(16, 185, 129)),
            AppState.RECORDING.value: create_tray_icon(QColor(239, 68, 68)),
            AppState.TRANSCRIBING.value: create_tray_icon(QColor(99, 102, 241)),
            AppState.LOADING_MODEL.value: create_tray_icon(QColor(245, 158, 11)),
            AppState.ERROR.value: create_tray_icon(QColor(248, 113, 113)),
        }
        super().__init__(self._icons[AppState.LOADING_MODEL.value], parent)
        self._active_hotkey = active_hotkey

        self._menu = QMenu()
        self._status_action = QAction("Durum: Başlatılıyor...", self._menu)
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)

        self._hotkey_action = QAction(f"Kısayol: {active_hotkey}", self._menu)
        self._hotkey_action.setEnabled(False)
        self._menu.addAction(self._hotkey_action)

        self._menu.addSeparator()

        self._toggle_action = QAction("Kaydı Başlat / Durdur", self._menu)
        self._toggle_action.triggered.connect(self.toggle_requested.emit)
        self._menu.addAction(self._toggle_action)

        self._settings_action = QAction("Ayarlar...", self._menu)
        self._settings_action.triggered.connect(self.settings_requested.emit)
        self._menu.addAction(self._settings_action)

        self._menu.addSeparator()

        self._quit_action = QAction("Çıkış", self._menu)
        self._quit_action.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)
        self.setToolTip(f"LocalDictate — {active_hotkey}")
        self.activated.connect(self._on_activated)

    def update_hotkey_label(self, active_hotkey: str) -> None:
        self._active_hotkey = active_hotkey
        self._hotkey_action.setText(f"Kısayol: {active_hotkey}")
        self.setToolTip(f"LocalDictate — {active_hotkey}")

    def on_state_changed(self, state: str, message: str) -> None:
        icon = self._icons.get(state, self._icons[AppState.IDLE.value])
        self.setIcon(icon)
        self._status_action.setText(f"Durum: {message}")
        self.setToolTip(f"LocalDictate ({message}) — {self._active_hotkey}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.settings_requested.emit()
