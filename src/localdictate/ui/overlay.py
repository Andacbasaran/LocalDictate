"""Floating, non-focus-stealing status pill HUD with live audio visualizer."""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..controller import AppState


class FloatingOverlay(QWidget):
    """Sleek floating pill overlay that never steals keyboard focus."""

    PILL_WIDTH = 244
    PILL_HEIGHT = 48

    def __init__(self, position: str = "bottom_center") -> None:
        super().__init__(None)
        self._position = position
        self._state = AppState.IDLE.value
        self._message = "Hazır"
        self._level = 0.0
        self._smooth_level = 0.0
        self._phase = 0.0
        self._record_start = 0.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(self.PILL_WIDTH, self.PILL_HEIGHT)

        # 30 FPS animation timer for waveform / processing pulse
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._tick)

        # Auto-hide timer for transient notifications (done / error / cancelled)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._auto_hide)

        self._reposition()

    def set_position(self, position: str) -> None:
        self._position = position
        self._reposition()

    def _reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        if self._position == "top_center":
            y = geo.y() + 24
        else:
            y = geo.y() + geo.height() - self.height() - 28
        self.move(x, y)

    def on_state_changed(self, state: str, message: str) -> None:
        self._state = state
        self._message = message
        self._hide_timer.stop()
        self._reposition()

        if state == AppState.RECORDING.value:
            self._record_start = time.monotonic()
            self._level = 0.0
            self._smooth_level = 0.0
            self._show_no_focus()
            self._anim_timer.start()
        elif state in (AppState.TRANSCRIBING.value, AppState.LOADING_MODEL.value):
            self._show_no_focus()
            self._anim_timer.start()
        elif state == AppState.ERROR.value:
            self._anim_timer.stop()
            self._show_no_focus()
            self._hide_timer.start(2800)
        else:
            # IDLE: briefly show confirmation if message is informative, else hide
            self._anim_timer.stop()
            if message and message != "Hazır":
                self._show_no_focus()
                self._hide_timer.start(1300)
            else:
                self.hide()

        self.update()

    def on_audio_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def _show_no_focus(self) -> None:
        if not self.isVisible():
            self.show()

    def _auto_hide(self) -> None:
        if self._state in (AppState.IDLE.value, AppState.ERROR.value):
            self.hide()

    def _tick(self) -> None:
        self._phase += 0.22
        self._smooth_level = self._smooth_level * 0.65 + self._level * 0.35
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        radius = rect.height() / 2.0

        # Background pill
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, QColor(18, 20, 26, 232))

        # Accent border color by state
        if self._state == AppState.RECORDING.value:
            accent = QColor(239, 68, 68)  # Crimson red
        elif self._state == AppState.TRANSCRIBING.value:
            accent = QColor(99, 102, 241)  # Indigo
        elif self._state == AppState.LOADING_MODEL.value:
            accent = QColor(245, 158, 11)  # Amber
        elif self._state == AppState.ERROR.value:
            accent = QColor(248, 113, 113)
        else:
            accent = QColor(16, 185, 129)  # Emerald

        pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 1.4)
        painter.setPen(pen)
        painter.drawPath(path)

        # Left status dot (pulsing during active states)
        dot_radius = 5.5
        if self._state in (
            AppState.RECORDING.value,
            AppState.TRANSCRIBING.value,
            AppState.LOADING_MODEL.value,
        ):
            pulse = 0.5 + 0.5 * math.sin(self._phase * 1.4)
            glow = QColor(accent.red(), accent.green(), accent.blue(), int(45 + 75 * pulse))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(14.0, 14.0, 20.0, 20.0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(QRectF(24.0 - dot_radius, 24.0 - dot_radius, dot_radius * 2, dot_radius * 2))

        if self._state == AppState.RECORDING.value:
            self._paint_waveform(painter, accent)
            elapsed = max(0.0, time.monotonic() - self._record_start)
            mins, secs = divmod(int(elapsed), 60)
            timer_text = f"{mins:02d}:{secs:02d}"
            painter.setPen(QColor(226, 232, 240))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(self.width() - 62, 0, 48, self.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                timer_text,
            )
        else:
            painter.setPen(QColor(241, 245, 249))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
            text_rect = QRectF(42.0, 0.0, self.width() - 56.0, self.height())
            elided = painter.fontMetrics().elidedText(
                self._message,
                Qt.TextElideMode.ElideRight,
                int(text_rect.width()),
            )
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                elided,
            )

        painter.end()

    def _paint_waveform(self, painter: QPainter, accent: QColor) -> None:
        """Draw 9 smooth reactive equalizer bars driven by live microphone RMS."""
        bar_count = 9
        bar_width = 4.0
        gap = 5.0
        start_x = 48.0
        center_y = self.height() / 2.0
        max_h = 24.0
        min_h = 4.0

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(bar_count):
            # Bell-curve envelope so center bars react strongest
            norm_pos = (i - (bar_count - 1) / 2.0) / ((bar_count - 1) / 2.0)
            envelope = 1.0 - 0.55 * (norm_pos * norm_pos)
            wave = 0.55 + 0.45 * math.sin(self._phase * 1.6 + i * 0.75)
            amp = max(0.08, self._smooth_level) * envelope * wave
            height = min(max_h, min_h + amp * (max_h - min_h))

            x = start_x + i * (bar_width + gap)
            y = center_y - height / 2.0
            bar_color = QColor(
                min(255, accent.red() + 15),
                min(255, accent.green() + 30),
                min(255, accent.blue() + 30),
                230,
            )
            painter.setBrush(bar_color)
            painter.drawRoundedRect(QRectF(x, y, bar_width, height), 2.0, 2.0)
