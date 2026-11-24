"""LocalDictate Studio 2.0 — Reusable HiDPI PyQt6 UI Widgets & Vector Icon Helpers.

Studio Graphite flat design system with Electric Violet (#8B5CF6) accent,
Emerald (#10B981) live status, and Rose (#E11D48) recording state.
"""

from __future__ import annotations

import math
import os
import sys
from collections import deque
from typing import Callable, Optional

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..hardware import get_app_base_dir

ACCENT_VIOLET = "#8B5CF6"
ACCENT_EMERALD = "#10B981"
ACCENT_ROSE = "#E11D48"
ACCENT_AMBER = "#F59E0B"


def make_flat_icon(kind: str, color_hex: str = "#FAFAFA", size: int = 14) -> QIcon:
    """Render crisp 2x HiDPI vector UI icons with zero emoji or font dependency."""
    px = max(16, int(size) * 2)
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(color_hex)

        if kind == "mic":
            pen = QPen(col, 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(
                QRectF(px * 0.36, px * 0.14, px * 0.28, px * 0.44),
                px * 0.14,
                px * 0.14,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(
                QRectF(px * 0.24, px * 0.26, px * 0.52, px * 0.44),
                180 * 16,
                180 * 16,
            )
            p.drawLine(QPointF(px * 0.50, px * 0.70), QPointF(px * 0.50, px * 0.85))
            p.drawLine(QPointF(px * 0.34, px * 0.85), QPointF(px * 0.66, px * 0.85))
        elif kind == "stop":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(
                int(px * 0.22), int(px * 0.22), int(px * 0.56), int(px * 0.56), 4, 4
            )
        elif kind == "play":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            poly = QPolygonF(
                [
                    QPointF(px * 0.28, px * 0.18),
                    QPointF(px * 0.82, px * 0.50),
                    QPointF(px * 0.28, px * 0.82),
                ]
            )
            p.drawPolygon(poly)
        elif kind == "copy":
            pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                int(px * 0.34), int(px * 0.30), int(px * 0.50), int(px * 0.54), 3, 3
            )
            p.drawLine(int(px * 0.22), int(px * 0.68), int(px * 0.22), int(px * 0.20))
            p.drawLine(int(px * 0.22), int(px * 0.20), int(px * 0.64), int(px * 0.20))
        elif kind == "paste":
            pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                int(px * 0.20), int(px * 0.22), int(px * 0.60), int(px * 0.64), 4, 4
            )
            p.drawRoundedRect(
                int(px * 0.36), int(px * 0.12), int(px * 0.28), int(px * 0.16), 3, 3
            )
            p.drawLine(int(px * 0.34), int(px * 0.50), int(px * 0.66), int(px * 0.50))
            p.drawLine(int(px * 0.34), int(px * 0.66), int(px * 0.56), int(px * 0.66))
        elif kind == "upload":
            pen = QPen(
                col,
                2.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.50, px * 0.66), QPointF(px * 0.50, px * 0.20))
            p.drawLine(QPointF(px * 0.32, px * 0.36), QPointF(px * 0.50, px * 0.18))
            p.drawLine(QPointF(px * 0.68, px * 0.36), QPointF(px * 0.50, px * 0.18))
            p.drawLine(QPointF(px * 0.20, px * 0.80), QPointF(px * 0.80, px * 0.80))
        elif kind == "export":
            pen = QPen(
                col,
                2.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.50, px * 0.20), QPointF(px * 0.50, px * 0.64))
            p.drawLine(QPointF(px * 0.32, px * 0.48), QPointF(px * 0.50, px * 0.66))
            p.drawLine(QPointF(px * 0.68, px * 0.48), QPointF(px * 0.50, px * 0.66))
            p.drawLine(QPointF(px * 0.20, px * 0.82), QPointF(px * 0.80, px * 0.82))
        elif kind == "gauge":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            bw = int(px * 0.17)
            p.drawRoundedRect(int(px * 0.16), int(px * 0.52), bw, int(px * 0.34), 2, 2)
            p.drawRoundedRect(int(px * 0.42), int(px * 0.30), bw, int(px * 0.56), 2, 2)
            p.drawRoundedRect(int(px * 0.68), int(px * 0.16), bw, int(px * 0.70), 2, 2)
        elif kind == "wave":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            bars = [(0.16, 0.34), (0.36, 0.66), (0.56, 0.48), (0.76, 0.26)]
            bw = max(2.0, px * 0.12)
            for bx, bh in bars:
                y = (px - px * bh) / 2.0
                p.drawRoundedRect(QRectF(px * bx, y, bw, px * bh), bw / 2.0, bw / 2.0)
        elif kind == "shield":
            pen = QPen(
                col,
                2.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(px * 0.50, px * 0.14)
            path.lineTo(px * 0.82, px * 0.28)
            path.lineTo(px * 0.78, px * 0.62)
            path.quadTo(px * 0.50, px * 0.88, px * 0.50, px * 0.88)
            path.quadTo(px * 0.22, px * 0.62, px * 0.22, px * 0.62)
            path.lineTo(px * 0.18, px * 0.28)
            path.closeSubpath()
            p.drawPath(path)
        elif kind == "refresh":
            pen = QPen(
                col,
                2.1,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(px * 0.20, px * 0.20, px * 0.60, px * 0.60)
            p.drawArc(rect, 35 * 16, 285 * 16)
            p.drawLine(QPointF(px * 0.78, px * 0.20), QPointF(px * 0.78, px * 0.38))
            p.drawLine(QPointF(px * 0.78, px * 0.38), QPointF(px * 0.60, px * 0.38))
        elif kind == "pin":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(px * 0.50, px * 0.34), px * 0.18, px * 0.18)
            pen = QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(px * 0.50, px * 0.50), QPointF(px * 0.50, px * 0.84))
        elif kind == "trash":
            pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.20, px * 0.26), QPointF(px * 0.80, px * 0.26))
            p.drawRoundedRect(
                QRectF(px * 0.28, px * 0.26, px * 0.44, px * 0.56), 3.0, 3.0
            )
            p.drawLine(QPointF(px * 0.40, px * 0.16), QPointF(px * 0.60, px * 0.16))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            r = px * 0.30
            p.drawEllipse(QPointF(px / 2.0, px / 2.0), r, r)
    finally:
        p.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix)


def create_app_pixmap(size: int = 64, prefer_file: bool = True) -> QPixmap:
    """Load or procedurally render the LocalDictate obsidian + Electric Violet voice-to-cursor logo."""
    target_px = max(16, int(size) * 2)
    if prefer_file:
        search_roots = [str(get_app_base_dir())]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and meipass not in search_roots:
            search_roots.append(meipass)
        for root in search_roots:
            for fname in ("app_icon.png", "app_icon.ico"):
                icon_path = os.path.join(root, "assets", fname)
                if os.path.exists(icon_path):
                    src_pix = QPixmap(icon_path)
                    if not src_pix.isNull():
                        scaled = src_pix.scaled(
                            target_px,
                            target_px,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        rounded = QPixmap(target_px, target_px)
                        rounded.fill(Qt.GlobalColor.transparent)
                        p = QPainter(rounded)
                        try:
                            p.setRenderHint(QPainter.RenderHint.Antialiasing)
                            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                            path = QPainterPath()
                            rad = target_px * 0.22
                            path.addRoundedRect(
                                0.0, 0.0, float(target_px), float(target_px), rad, rad
                            )
                            p.setClipPath(path)
                            p.drawPixmap(0, 0, scaled)
                        finally:
                            p.end()
                        rounded.setDevicePixelRatio(2.0)
                        return rounded

    # Procedural flat brand tile matching assets/app_icon.svg
    pix = QPixmap(target_px, target_px)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = target_px / 512.0

        # Matte Obsidian Tile
        painter.setBrush(QColor("#111114"))
        painter.setPen(QPen(QColor("#27272E"), max(1.0, 6.0 * k)))
        painter.drawRoundedRect(
            QRectF(12 * k, 12 * k, 488 * k, 488 * k), 114 * k, 114 * k
        )

        # Architectural Voice Wave Bars (left-center, crisp white + violet core)
        painter.setPen(Qt.PenStyle.NoPen)
        bars = [
            (108, 212, 28, 88, "#52525B"),
            (156, 152, 32, 208, "#FAFAFA"),
            (208, 118, 36, 276, "#8B5CF6"),
            (264, 170, 32, 172, "#FAFAFA"),
        ]
        for bx, by, bw, bh, color_hex in bars:
            painter.setBrush(QColor(color_hex))
            painter.drawRoundedRect(
                QRectF(bx * k, by * k, bw * k, bh * k), (bw * 0.5) * k, (bw * 0.5) * k
            )

        # Dictated Text Track & Live Cursor Bar (right)
        painter.setBrush(QColor("#3F3F46"))
        painter.drawRoundedRect(QRectF(324 * k, 206 * k, 74 * k, 24 * k), 12 * k, 12 * k)
        painter.setBrush(QColor("#A1A1AA"))
        painter.drawRoundedRect(QRectF(324 * k, 248 * k, 54 * k, 24 * k), 12 * k, 12 * k)
        # Electric Violet typing caret
        painter.setBrush(QColor("#8B5CF6"))
        painter.drawRoundedRect(QRectF(392 * k, 242 * k, 16 * k, 68 * k), 8 * k, 8 * k)
        # Emerald offline dot accent
        painter.setBrush(QColor("#10B981"))
        painter.drawEllipse(QRectF(324 * k, 290 * k, 22 * k, 22 * k))
    finally:
        painter.end()
    pix.setDevicePixelRatio(2.0)
    return pix


def create_app_icon() -> QIcon:
    search_roots = [str(get_app_base_dir())]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    for root in search_roots:
        for fname in ("app_icon.ico", "app_icon.png"):
            ico_path = os.path.join(root, "assets", fname)
            if os.path.exists(ico_path):
                return QIcon(ico_path)
    return QIcon(create_app_pixmap(64))


class SidebarNavButton(QPushButton):
    """Studio 2.0 sidebar navigation item with Electric Violet active dot and status/count badge."""

    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._label_text = label
        self._badge_text = ""
        self._badge_kind = "muted"  # 'muted' | 'live' | 'rec' | 'loading'
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        super().setText("")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(9)

        self._dot = QFrame(self)
        self._dot.setFixedSize(6, 6)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._dot)

        self._lbl = QLabel(label, self)
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._lbl, stretch=1)

        self._badge = QLabel("", self)
        self._badge.setFixedHeight(19)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._badge.hide()
        lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self._refresh_style()

    def set_nav_text(self, label: str) -> None:
        self._label_text = label
        self._lbl.setText(label)

    def nav_text(self) -> str:
        return self._lbl.text()

    def set_badge(self, text: str, kind: str = "muted") -> None:
        self._badge_text = str(text or "").strip()
        self._badge_kind = kind
        if not self._badge_text:
            self._badge.hide()
            return
        self._badge.setText(self._badge_text)
        if kind == "live":
            self._badge.setStyleSheet(
                "color: #10B981; background-color: #0D231B; border: 1px solid #174131; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        elif kind == "rec":
            self._badge.setStyleSheet(
                "color: #FB7185; background-color: #2B1018; border: 1px solid #591C2E; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        elif kind == "loading":
            self._badge.setStyleSheet(
                "color: #A78BFA; background-color: #1C162E; border: 1px solid #352759; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        else:
            self._badge.setStyleSheet(
                "color: #A1A1AA; background-color: #1B1B21; border: 1px solid #2A2A32; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        self._badge.show()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                "QPushButton { background-color: #1E1E24; border: 1px solid #2C2C35; border-radius: 7px; }"
            )
            self._dot.setStyleSheet("background-color: #8B5CF6; border-radius: 2px; border: none;")
            self._lbl.setStyleSheet(
                "color: #FAFAFA; font-size: 9pt; font-weight: 600; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 7px; }"
                "QPushButton:hover { background-color: #18181D; }"
            )
            self._dot.setStyleSheet("background-color: #52525B; border-radius: 2px; border: none;")
            self._lbl.setStyleSheet(
                "color: #A1A1AA; font-size: 9pt; font-weight: 500; background: transparent; border: none;"
            )


class FlatSwitch(QCheckBox):
    """Studio 2.0 monochrome / Electric Violet flat toggle switch (QCheckBox-compatible)."""

    def __init__(
        self,
        text: str = "",
        accent_hex: str = "#FAFAFA",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self._accent_hex = accent_hex
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        return QSize(34 + 10 + text_w + 8, max(24, fm.height() + 6))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            track_w, track_h = 32, 17
            y = (self.height() - track_h) // 2
            checked = self.isChecked()

            if checked:
                track_col = QColor(self._accent_hex)
                border_col = QColor(self._accent_hex)
                knob_col = (
                    QColor("#09090B")
                    if self._accent_hex.upper() == "#FAFAFA"
                    else QColor("#FFFFFF")
                )
            else:
                track_col = QColor("#24242B")
                border_col = QColor("#32323B")
                knob_col = QColor("#A1A1AA")

            p.setBrush(track_col)
            p.setPen(QPen(border_col, 1))
            p.drawRoundedRect(1, y, track_w, track_h, track_h / 2.0, track_h / 2.0)

            knob_d = 11
            knob_x = (track_w - knob_d - 2) if checked else 4
            knob_y = y + (track_h - knob_d) // 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(knob_col)
            p.drawEllipse(knob_x, knob_y, knob_d, knob_d)

            text_col = (
                QColor("#E4E4E7")
                if (self.isEnabled() and checked)
                else (QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B"))
            )
            p.setPen(text_col)
            p.setFont(self.font())
            text_rect = QRect(track_w + 9, 0, self.width() - track_w - 9, self.height())
            p.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self.text(),
            )
        finally:
            p.end()


class FlatComboBox(QComboBox):
    """Flat QComboBox with a consistent custom vector downward chevron on all OSes."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_before_popup: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_before_popup = on_before_popup
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)

    def showPopup(self) -> None:
        if callable(self._on_before_popup):
            try:
                self._on_before_popup()
            except Exception:
                pass
        super().showPopup()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            col = QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B")
            pen = QPen(
                col,
                1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            cx = self.width() - 15
            cy = self.height() // 2
            p.drawLine(QPointF(cx - 3.6, cy - 1.8), QPointF(cx, cy + 2.0))
            p.drawLine(QPointF(cx, cy + 2.0), QPointF(cx + 3.6, cy - 1.8))
        finally:
            p.end()


class TelemetryCard(QFrame):
    """Studio 2.0 flat metric/telemetry card with 2px accent indicator bar."""

    def __init__(
        self,
        title: str,
        badge_text: str,
        initial_val: str,
        sub_text: str,
        accent_hex: str = ACCENT_VIOLET,
        initial_pct: int = 30,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.accent_hex = accent_hex
        self.setObjectName("telemetryCard")
        self.setStyleSheet(
            """
            QFrame#telemetryCard {
                background-color: #141417;
                border: 1px solid #24242A;
                border-radius: 9px;
            }
            QFrame#telemetryCard QLabel {
                background-color: transparent;
                border: none;
            }
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #71717A; font-size: 7.2pt; font-weight: 700; letter-spacing: 0.6px;"
        )
        hdr.addWidget(self.lbl_title)

        self.lbl_badge = QLabel(badge_text)
        self.lbl_badge.setStyleSheet("color: #71717A; font-size: 7pt; font-weight: 600;")
        hdr.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(hdr)

        self.lbl_val = QLabel(initial_val)
        self.lbl_val.setStyleSheet(
            "color: #FAFAFA; font-size: 14pt; font-weight: 700; letter-spacing: -0.3px;"
        )
        lay.addWidget(self.lbl_val)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(max(4, min(100, int(initial_pct))))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(2)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: none;
                background-color: #24242A;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_hex};
                border-radius: 1px;
            }}
            """
        )
        lay.addWidget(self.bar)

        self.lbl_sub = QLabel(sub_text)
        self.lbl_sub.setStyleSheet("color: #71717A; font-size: 7.3pt; font-weight: 500;")
        lay.addWidget(self.lbl_sub)

    def set_title(self, title: str) -> None:
        self.lbl_title.setText(title)

    def set_metric(
        self,
        val_text: str,
        sub_text: Optional[str] = None,
        badge_text: Optional[str] = None,
        bar_pct: Optional[int] = None,
    ) -> None:
        self.lbl_val.setText(val_text)
        if sub_text is not None:
            self.lbl_sub.setText(sub_text)
        if badge_text is not None:
            self.lbl_badge.setText(badge_text)
        if bar_pct is not None:
            self.bar.setValue(max(4, min(100, int(round(bar_pct)))))


class LiveWaveformBar(QWidget):
    """24-bar real-time rolling studio waveform visualizer for the Live Dictation Stage."""

    def __init__(self, bar_count: int = 24, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bar_count = max(8, int(bar_count))
        self._levels: deque[float] = deque([0.08] * self._bar_count, maxlen=self._bar_count)
        self._state = "idle"
        self._phase = 0.0
        self.setMinimumHeight(64)
        self.setMaximumHeight(74)

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def push_level(self, level: float) -> None:
        clamped = max(0.04, min(1.0, float(level)))
        self._levels.append(clamped)
        self._phase += 0.25
        self.update()

    def set_levels(self, levels: list[float]) -> None:
        """Populate explicit waveform bars (useful for snapshots, previews, and tests)."""
        self._levels.clear()
        padded = ([0.08] * max(0, self._bar_count - len(levels))) + list(levels[-self._bar_count :])
        for v in padded:
            self._levels.append(max(0.04, min(1.0, float(v))))
        self.update()

    def reset_idle(self) -> None:
        self._levels.clear()
        for i in range(self._bar_count):
            norm = abs((i - (self._bar_count - 1) / 2.0) / ((self._bar_count - 1) / 2.0))
            self._levels.append(0.10 + 0.12 * (1.0 - norm))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = float(self.width())
            h = float(self.height())

            # Subtle dark studio bay surface
            p.setPen(QPen(QColor("#1F1F26"), 1.0))
            p.setBrush(QColor("#0C0C0F"))
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 8.0, 8.0)

            # Subtle baseline
            center_y = h / 2.0
            p.setPen(QPen(QColor("#1E1E26"), 1.0))
            p.drawLine(QPointF(16.0, center_y), QPointF(w - 16.0, center_y))

            if self._state == "recording":
                base_col = QColor(ACCENT_ROSE)
                peak_col = QColor("#FB7185")
            elif self._state in ("transcribing", "refining"):
                base_col = QColor(ACCENT_VIOLET)
                peak_col = QColor("#C4B5FD")
            elif self._state == "loading_model":
                base_col = QColor(ACCENT_AMBER)
                peak_col = QColor("#FDE68A")
            else:
                base_col = QColor(ACCENT_VIOLET)
                peak_col = QColor("#A78BFA")

            pad_x = 24.0
            avail_w = max(40.0, w - 2.0 * pad_x)
            slot_w = avail_w / self._bar_count
            bar_w = max(4.0, min(9.0, slot_w * 0.48))
            max_bar_h = h - 18.0
            min_bar_h = 5.0

            p.setPen(Qt.PenStyle.NoPen)
            values = list(self._levels)
            for idx, lvl in enumerate(values):
                norm_pos = (idx - (self._bar_count - 1) / 2.0) / max(1.0, (self._bar_count - 1) / 2.0)
                envelope = 1.0 - 0.35 * (norm_pos * norm_pos)
                if self._state in ("transcribing", "refining"):
                    amp = 0.25 + 0.55 * (0.5 + 0.5 * math.sin(self._phase + idx * 0.45)) * envelope
                else:
                    amp = lvl * envelope

                bar_h = max(min_bar_h, min(max_bar_h, min_bar_h + amp * (max_bar_h - min_bar_h)))
                x = pad_x + idx * slot_w + (slot_w - bar_w) / 2.0
                y = center_y - bar_h / 2.0

                col = peak_col if amp > 0.55 else base_col
                alpha = 235 if self._state != "idle" else 165
                p.setBrush(QColor(col.red(), col.green(), col.blue(), alpha))
                p.drawRoundedRect(QRectF(x, y, bar_w, bar_h), bar_w / 2.0, bar_w / 2.0)
        finally:
            p.end()
