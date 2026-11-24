"""Floating HUD 2.0: non-focus-stealing status pill with 20-bar rolling waveform & Mode+Lang micro-pill."""

from __future__ import annotations

import math
import time
from collections import deque

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..controller import AppState
from ..hardware import get_ui_font_family
from ..platform_utils import apply_win32_overlay_no_activate, configure_macos_overlay_window

MODE_SHORT_LABELS: dict[str, str] = {
    "cleanup": "CLEAN",
    "formal": "FORMAL",
    "concise": "CONCISE",
    "code": "CODE",
    "bullet_notes": "NOTES",
    "git_commit": "GIT",
    "translate_en": "TR→EN",
}


class FloatingOverlay(QWidget):
    """Sleek Studio 2.0 floating pill overlay that never steals focus on Win32, macOS Cocoa, or Linux."""

    PILL_WIDTH = 330
    PILL_HEIGHT = 50
    WAVE_BARS = 20

    def __init__(
        self,
        position: str = "bottom_center",
        mode: str = "cleanup",
        language: str = "auto",
    ) -> None:
        super().__init__(None)
        self._position = position
        self._state = AppState.IDLE.value
        self._message = "Ready"
        self._mode = mode
        self._language = language
        self._level = 0.0
        self._smooth_level = 0.0
        self._phase = 0.0
        self._record_start = 0.0
        self._os_styled = False
        self._wave_history: deque[float] = deque([0.08] * self.WAVE_BARS, maxlen=self.WAVE_BARS)
        self._ui_font = get_ui_font_family()

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

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._auto_hide)

        self._reposition()

    def _apply_os_overlay_flags(self) -> None:
        """Apply native Win32 WS_EX_NOACTIVATE or macOS Cocoa NSStatusWindowLevel + hidesOnDeactivate=NO."""
        if self._os_styled:
            return
        try:
            apply_win32_overlay_no_activate(int(self.winId()))
            configure_macos_overlay_window(self)
            self._os_styled = True
        except Exception:
            pass

    def set_position(self, position: str) -> None:
        self._position = position
        self._reposition()

    def set_context_badge(self, mode: str, language: str) -> None:
        self._mode = mode or "cleanup"
        self._language = language or "auto"
        self.update()

    def _micro_pill_text(self) -> str:
        mode_lbl = MODE_SHORT_LABELS.get(self._mode, self._mode.upper()[:6])
        lang_lbl = (self._language or "auto").upper()[:4]
        if self._mode == "translate_en":
            return mode_lbl
        return f"{mode_lbl} · {lang_lbl}"

    def _reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        if self._position == "top_center":
            y = geo.y() + 26
        else:
            y = geo.y() + geo.height() - self.height() - 32
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
            self._wave_history.clear()
            self._wave_history.extend([0.08] * self.WAVE_BARS)
            self._show_no_focus()
            self._anim_timer.start()
        elif state in (
            AppState.TRANSCRIBING.value,
            AppState.REFINING.value,
            AppState.LOADING_MODEL.value,
        ):
            self._show_no_focus()
            self._anim_timer.start()
        elif state == AppState.ERROR.value:
            self._anim_timer.stop()
            self._show_no_focus()
            self._hide_timer.start(2800)
        else:
            self._anim_timer.stop()
            if message and message.lower() not in ("ready", "hazır"):
                self._show_no_focus()
                self._hide_timer.start(1500)
            else:
                self.hide()

        self.update()

    def on_audio_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def _show_no_focus(self) -> None:
        if not self.isVisible():
            self.show()
            self._apply_os_overlay_flags()

    def _auto_hide(self) -> None:
        if self._state in (AppState.IDLE.value, AppState.ERROR.value):
            self.hide()

    def _tick(self) -> None:
        self._phase += 0.22
        self._smooth_level = self._smooth_level * 0.58 + self._level * 0.42
        self._wave_history.append(max(0.07, self._smooth_level))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
            radius = rect.height() / 2.0

            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            painter.fillPath(path, QColor(14, 14, 18, 242))

            if self._state == AppState.RECORDING.value:
                accent = QColor("#E11D48")  # Rose
            elif self._state == AppState.TRANSCRIBING.value:
                accent = QColor("#8B5CF6")  # Electric Violet
            elif self._state == AppState.REFINING.value:
                accent = QColor("#A78BFA")  # Soft Violet
            elif self._state == AppState.LOADING_MODEL.value:
                accent = QColor("#F59E0B")  # Amber
            elif self._state == AppState.ERROR.value:
                accent = QColor("#FB7185")
            else:
                accent = QColor("#10B981")  # Emerald

            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 190), 1.4)
            painter.setPen(pen)
            painter.drawPath(path)

            # Pulsing status indicator dot
            dot_radius = 5.0
            if self._state in (
                AppState.RECORDING.value,
                AppState.TRANSCRIBING.value,
                AppState.REFINING.value,
                AppState.LOADING_MODEL.value,
            ):
                pulse = 0.5 + 0.5 * math.sin(self._phase * 1.4)
                glow = QColor(accent.red(), accent.green(), accent.blue(), int(45 + 80 * pulse))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(QRectF(14.0, 15.0, 20.0, 20.0))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(
                QRectF(24.0 - dot_radius, 25.0 - dot_radius, dot_radius * 2, dot_radius * 2)
            )

            # Active Mode + Language micro-pill on the right
            badge_txt = self._micro_pill_text()
            badge_font = QFont(self._ui_font, 7, QFont.Weight.Bold)
            painter.setFont(badge_font)
            fm = painter.fontMetrics()
            badge_w = min(92, fm.horizontalAdvance(badge_txt) + 14)
            badge_h = 20
            badge_x = self.width() - badge_w - 14
            badge_y = (self.height() - badge_h) / 2.0

            painter.setPen(QPen(QColor("#2B2B35"), 1.0))
            painter.setBrush(QColor("#1A1A22"))
            painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), 6.0, 6.0)
            painter.setPen(QColor("#C4B5FD"))
            painter.drawText(
                QRectF(badge_x, badge_y, badge_w, badge_h),
                Qt.AlignmentFlag.AlignCenter,
                badge_txt,
            )

            if self._state == AppState.RECORDING.value:
                self._paint_waveform(painter, accent, right_limit=badge_x - 52)
                elapsed = max(0.0, time.monotonic() - self._record_start)
                mins, secs = divmod(int(elapsed), 60)
                timer_text = f"{mins:02d}:{secs:02d}"
                painter.setPen(QColor("#E4E4E7"))
                painter.setFont(QFont(self._ui_font, 8, QFont.Weight.DemiBold))
                painter.drawText(
                    QRectF(badge_x - 46, 0, 40, self.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    timer_text,
                )
            else:
                painter.setPen(QColor("#FAFAFA"))
                painter.setFont(QFont(self._ui_font, 9, QFont.Weight.Medium))
                text_w = max(40.0, badge_x - 50.0)
                text_rect = QRectF(42.0, 0.0, text_w, self.height())
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
        finally:
            painter.end()

    def _paint_waveform(self, painter: QPainter, accent: QColor, right_limit: float) -> None:
        start_x = 42.0
        avail = max(40.0, right_limit - start_x)
        bar_count = self.WAVE_BARS
        slot = avail / bar_count
        bar_width = max(2.4, min(4.0, slot * 0.56))
        center_y = self.height() / 2.0
        max_h = 26.0
        min_h = 4.0

        painter.setPen(Qt.PenStyle.NoPen)
        samples = list(self._wave_history)
        for i, raw_amp in enumerate(samples):
            norm_pos = (i - (bar_count - 1) / 2.0) / max(1.0, (bar_count - 1) / 2.0)
            envelope = 1.0 - 0.38 * (norm_pos * norm_pos)
            height = min(max_h, min_h + raw_amp * envelope * (max_h - min_h))
            x = start_x + i * slot + (slot - bar_width) / 2.0
            y = center_y - height / 2.0
            bar_color = QColor(
                min(255, accent.red() + 20),
                min(255, accent.green() + 35),
                min(255, accent.blue() + 35),
                235,
            )
            painter.setBrush(bar_color)
            painter.drawRoundedRect(QRectF(x, y, bar_width, height), bar_width / 2.0, bar_width / 2.0)
