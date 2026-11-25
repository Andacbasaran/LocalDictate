"""LocalDictate Studio 2.0 — Flagship PyQt6 Desktop Interface (960x640, Studio Graphite + Electric Violet)."""

from __future__ import annotations

import logging
import re
import sys
import time
import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pyperclip
from PyQt6.QtCore import QRect, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..audio import AudioRecorder, detect_speech_segments, list_input_devices, resample_audio
from ..config import (
    AVAILABLE_LANGUAGES,
    AVAILABLE_MODELS,
    HOTKEY_MODES,
    LLM_BACKENDS,
)
from ..controller import AppState, DictationController, DictationOutcome
from ..hardware import (
    PROFILE_AUTO,
    PROFILE_BALANCED,
    PROFILE_ECO,
    PROFILE_PERFORMANCE,
    format_hardware_summary,
    get_ui_font_family,
)
from ..history import HistoryEntry, HistoryStore
from ..hotkeys import format_hotkey_display
from ..i18n import LanguageManager
from ..platform_utils import check_accessibility_permission
from ..postprocess import fetch_llm_models
from ..snippets import apply_replacements, apply_voice_commands, merge_starter_pack
from ..transcriber import is_model_cached
from ..updater import UpdateCheckerThread, UpdateInfo, is_trusted_update_url
from .widgets import (
    ACCENT_AMBER,
    ACCENT_EMERALD,
    ACCENT_VIOLET,
    FlatComboBox,
    FlatSwitch,
    LiveWaveformBar,
    SidebarNavButton,
    TelemetryCard,
    create_app_icon,
    create_app_pixmap,
    make_flat_icon,
)

logger = logging.getLogger(__name__)

AUDIO_FILE_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}

MODE_PILLS: list[tuple[str, str]] = [
    ("cleanup", "mode_cleanup"),
    ("formal", "mode_formal"),
    ("concise", "mode_concise"),
    ("code", "mode_code"),
    ("bullet_notes", "mode_bullet_notes"),
    ("git_commit", "mode_git_commit"),
    ("translate_en", "mode_translate_en"),
]


def _escape_rule_value(val: str) -> str:
    """Escape backslashes and newlines so multiline snippets round-trip on one line."""
    normalized = str(val).replace("\r\n", "\n").replace("\r", "")
    return normalized.replace("\\", "\\\\").replace("\n", "\\n")


def _unescape_rule_value(raw: str) -> str:
    """Single-pass unescape for \\\\, \\n, and \\r in snippet rule values."""
    def _sub(match: re.Match[str]) -> str:
        seq = match.group(0)
        if seq == r"\\":
            return "\\"
        if seq == r"\n":
            return "\n"
        if seq == r"\r":
            return ""
        return seq

    return re.sub(r"\\(\\|n|r)", _sub, raw)


def _format_rules_text(rules: dict[str, str]) -> str:
    lines: list[str] = []
    for k, v in rules.items():
        key = str(k).replace("\r", "").replace("\n", " ").strip()
        if not key:
            continue
        lines.append(f"{key} -> {_escape_rule_value(v)}")
    return "\n".join(lines)


def _parse_rules_text(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        if not raw_line.strip() or "->" not in raw_line:
            continue
        src, dst = raw_line.split("->", 1)
        src = src.strip()
        dst = dst.lstrip(" \t")
        if src:
            parsed[src] = _unescape_rule_value(dst)
    return parsed


class _LLMTestThread(QThread):
    """Non-blocking background probe for Ollama / OpenAI-compatible LLM endpoints."""

    finished_probe = pyqtSignal(list, str)  # (models_list, error_str)

    def __init__(
        self,
        backend: str,
        base_url: str,
        api_key: str,
        offline_only: bool,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self._base_url = base_url
        self._api_key = api_key
        self._offline_only = offline_only

    def run(self) -> None:
        try:
            models = fetch_llm_models(
                backend=self._backend,
                base_url=self._base_url,
                api_key=self._api_key,
                offline_only=self._offline_only,
                timeout=3.5,
            )
            if not self.isInterruptionRequested():
                self.finished_probe.emit(models, "")
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.finished_probe.emit([], str(exc))


class _QuickBenchmarkThread(QThread):
    """In-app deterministic local pipeline benchmark (VAD, Resample, Snippets, SQLite Search)."""

    benchmark_done = pyqtSignal(dict)

    def __init__(self, history: Optional[HistoryStore] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._history = history

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        # 1. Resample 48kHz -> 16kHz (2s synthetic clip)
        rng = np.random.default_rng(7)
        clip_48k = (rng.standard_normal(48_000 * 2) * 0.05).astype(np.float32)
        t0 = time.perf_counter()
        for _ in range(5):
            if self.isInterruptionRequested():
                return
            clip_16k = resample_audio(clip_48k, 48_000, 16_000)
        resample_ms = ((time.perf_counter() - t0) / 5.0) * 1000.0

        # 2. Energy VAD
        t0 = time.perf_counter()
        for _ in range(25):
            if self.isInterruptionRequested():
                return
            detect_speech_segments(clip_16k, 16_000)
        vad_ms = ((time.perf_counter() - t0) / 25.0) * 1000.0

        # 3. Voice commands + snippet expansion
        sample = "hello team comma new line we migrated node.js and c++ to .env today date period"
        rules = {"today date": "{{iso_date}}", "c++": "C++", "node.js": "Node.js", ".env": "`.env`"}
        t0 = time.perf_counter()
        for _ in range(200):
            if self.isInterruptionRequested():
                return
            txt = apply_voice_commands(sample)
            apply_replacements(txt, rules)
        snippet_ms = ((time.perf_counter() - t0) / 200.0) * 1000.0

        # 4. History search latency
        search_ms = 0.25
        if self._history is not None:
            t0 = time.perf_counter()
            for _ in range(20):
                if self.isInterruptionRequested():
                    return
                self._history.list_recent(limit=50, query="istanbul")
            search_ms = ((time.perf_counter() - t0) / 20.0) * 1000.0

        if not self.isInterruptionRequested():
            self.benchmark_done.emit(
                {
                    "resample_ms": resample_ms,
                    "vad_ms": vad_ms,
                    "snippet_ms": snippet_ms,
                    "search_ms": search_ms,
                }
            )


class StudioWindow(QMainWindow):
    """Flagship LocalDictate Studio 2.0 desktop window with sidebar rail & 3 workspace tabs."""

    config_applied = pyqtSignal(object)  # emits updated AppConfig

    def __init__(
        self,
        controller: DictationController,
        history: HistoryStore,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.history = history
        self.i18n = LanguageManager(controller.config.ui_language)
        self._ui_font = get_ui_font_family()

        self._force_quit = False
        self._active_tab = 0
        self._pinned_only = False
        self._mic_testing = False
        self._mic_test_recorder: Optional[AudioRecorder] = None
        self._llm_test_thread: Optional[_LLMTestThread] = None
        self._update_thread: Optional[UpdateCheckerThread] = None
        self._bench_thread: Optional[_QuickBenchmarkThread] = None
        self._latest_release_url: str = ""
        self._mode_buttons: Dict[str, QPushButton] = {}
        self._history_entries: List[HistoryEntry] = []

        self.setWindowTitle(f"LocalDictate v{__version__} — Offline Voice Studio")
        self.setWindowIcon(create_app_icon())
        self.setAcceptDrops(True)

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1440, 900)
        min_w = min(840, max(760, avail.width() - 40))
        min_h = min(580, max(520, avail.height() - 40))
        init_w = min(960, max(min_w, avail.width() - 60))
        init_h = min(640, max(min_h, avail.height() - 60))
        self.setMinimumSize(min_w, min_h)
        self.resize(init_w, init_h)

        # Debounced history search timer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self.refresh_history)

        # Mic VU meter test polling timer (safe main-thread polling)
        self._mic_test_timer = QTimer(self)
        self._mic_test_timer.setInterval(33)
        self._mic_test_timer.timeout.connect(self._poll_mic_test)

        self._build_ui()
        self._connect_controller_signals()
        self._sync_ui_from_config()
        self.refresh_history()
        self.switch_tab(0)

    def _build_ui(self) -> None:
        ui_font = self._ui_font
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget#centralWidget, QScrollArea {{
                background-color: #0A0A0C;
                color: #FAFAFA;
                font-family: '{ui_font}', 'Segoe UI', 'Inter', -apple-system, sans-serif;
            }}
            QLabel {{
                background-color: transparent;
                color: #E4E4E7;
                font-family: '{ui_font}', 'Segoe UI', 'Inter', -apple-system, sans-serif;
            }}
            QFrame#sidebarRail {{
                background-color: #111113;
                border: none;
                border-right: 1px solid #222227;
            }}
            QFrame#studioPanel {{
                background-color: #141417;
                border: 1px solid #24242A;
                border-radius: 10px;
            }}
            QFrame#stagePanel {{
                background-color: #111114;
                border: 1px solid #24242A;
                border-radius: 11px;
            }}
            QPushButton {{
                background-color: #1B1B21;
                color: #E4E4E7;
                border: 1px solid #2B2B34;
                border-radius: 7px;
                padding: 6px 12px;
                font-size: 8.6pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #23232B;
                border-color: #3F3F4A;
                color: #FFFFFF;
            }}
            QPushButton:pressed {{
                background-color: #16161B;
            }}
            QPushButton:disabled {{
                background-color: #121216;
                color: #52525B;
                border-color: #1E1E24;
            }}
            QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
                background-color: #0F0F13;
                color: #FAFAFA;
                border: 1px solid #26262E;
                border-radius: 7px;
                padding: 6px 10px;
                font-size: 8.6pt;
                selection-background-color: #8B5CF6;
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border-color: #8B5CF6;
            }}
            QComboBox {{
                background-color: #141417;
                border: 1px solid #26262E;
                border-radius: 8px;
                padding: 5px 26px 5px 10px;
                min-height: 22px;
                color: #FAFAFA;
                font-size: 8.6pt;
                font-weight: 500;
            }}
            QComboBox:hover {{
                border-color: #3F3F4A;
                background-color: #1A1A20;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #16161A;
                color: #F4F4F5;
                selection-background-color: #2A243C;
                selection-color: #FFFFFF;
                border: 1px solid #32323C;
                outline: none;
                padding: 4px;
            }}
            QListWidget {{
                background-color: #0E0E12;
                border: 1px solid #222228;
                border-radius: 9px;
                color: #E4E4E7;
                padding: 5px;
                outline: none;
            }}
            QListWidget::item {{
                background: transparent;
                border: none;
                padding: 0px;
                margin-bottom: 6px;
            }}
            QListWidget::item:selected {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 5px;
                margin: 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background: #2A2A32;
                border-radius: 2px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #52525E;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            """
        )

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background-color: #0A0A0C; border: none; }")
        self.stack.addWidget(self._build_studio_page())
        self.stack.addWidget(self._build_history_page())
        self.stack.addWidget(self._build_settings_page())
        root_layout.addWidget(self.stack, stretch=1)

    # ═══════════════════════════════════════════════════════════════════════
    # SIDEBAR RAIL (218px)
    # ═══════════════════════════════════════════════════════════════════════
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebarRail")
        sidebar.setFixedWidth(218)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(14, 18, 14, 14)
        sb_lay.setSpacing(16)

        # Brand Header
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(2, 0, 2, 0)
        brand_row.setSpacing(10)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_app_pixmap(30))
        logo_lbl.setFixedSize(30, 30)
        logo_lbl.setStyleSheet("border: none; background: transparent;")
        brand_row.addWidget(logo_lbl)

        brand_txt = QVBoxLayout()
        brand_txt.setSpacing(0)
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        title_lbl = QLabel("LocalDictate")
        title_lbl.setFont(QFont(self._ui_font, 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FAFAFA; letter-spacing: -0.2px;")
        top_row.addWidget(title_lbl)

        ver_lbl = QLabel(f"v{__version__}")
        ver_lbl.setStyleSheet("color: #71717A; font-size: 7.4pt; font-weight: 600;")
        top_row.addWidget(ver_lbl)
        top_row.addStretch(1)
        brand_txt.addLayout(top_row)

        self.lbl_app_subtitle = QLabel(self.i18n.t("app_subtitle"))
        self.lbl_app_subtitle.setStyleSheet("color: #71717A; font-size: 7.5pt; font-weight: 500;")
        brand_txt.addWidget(self.lbl_app_subtitle)
        brand_row.addLayout(brand_txt, stretch=1)
        sb_lay.addLayout(brand_row)

        # Main Navigation Tabs
        nav_col = QVBoxLayout()
        nav_col.setSpacing(4)
        self.btn_nav_studio = SidebarNavButton(self.i18n.t("nav_studio"))
        self.btn_nav_history = SidebarNavButton(self.i18n.t("nav_history"))
        self.btn_nav_settings = SidebarNavButton(self.i18n.t("nav_settings"))

        self.btn_nav_studio.set_badge(self.i18n.t("badge_ready"), kind="live")
        for idx, btn in enumerate((self.btn_nav_studio, self.btn_nav_history, self.btn_nav_settings)):
            btn.clicked.connect(lambda _c=False, i=idx: self.switch_tab(i))
            nav_col.addWidget(btn)
        sb_lay.addLayout(nav_col)

        sb_lay.addStretch(1)

        # Bottom Engine Status Card
        status_card = QFrame()
        status_card.setStyleSheet(
            """
            QFrame {
                background-color: #151519;
                border: 1px solid #24242A;
                border-radius: 8px;
            }
            """
        )
        sc_lay = QVBoxLayout(status_card)
        sc_lay.setContentsMargins(11, 10, 11, 10)
        sc_lay.setSpacing(6)

        st_top = QHBoxLayout()
        st_top.setSpacing(7)
        self._sidebar_dot = QFrame()
        self._sidebar_dot.setFixedSize(7, 7)
        self._sidebar_dot.setStyleSheet("background-color: #10B981; border-radius: 3px; border: none;")
        st_top.addWidget(self._sidebar_dot)

        self.lbl_engine_status = QLabel(self.i18n.t("status_ready"))
        self.lbl_engine_status.setStyleSheet(
            "color: #FAFAFA; font-size: 8.3pt; font-weight: 600; border: none; background: transparent;"
        )
        st_top.addWidget(self.lbl_engine_status, stretch=1)
        sc_lay.addLayout(st_top)

        self.lbl_engine_meta = QLabel("INT8 (small) · 0 MB VRAM")
        self.lbl_engine_meta.setStyleSheet(
            "color: #71717A; font-size: 7.2pt; font-weight: 600; border: none; background: transparent;"
        )
        sc_lay.addWidget(self.lbl_engine_meta)

        self.engine_progress = QProgressBar()
        self.engine_progress.setRange(0, 100)
        self.engine_progress.setValue(100)
        self.engine_progress.setTextVisible(False)
        self.engine_progress.setFixedHeight(2)
        self.engine_progress.setStyleSheet(
            """
            QProgressBar { border: none; border-radius: 1px; background-color: #24242A; }
            QProgressBar::chunk { background-color: #8B5CF6; border-radius: 1px; }
            """
        )
        sc_lay.addWidget(self.engine_progress)
        sb_lay.addWidget(status_card)

        # Hotkey Keycaps Footer
        hk_row = QHBoxLayout()
        hk_row.setSpacing(5)
        self.lbl_hotkey_cap = QLabel(format_hotkey_display(self.controller.config.active_hotkey))
        self.lbl_hotkey_cap.setStyleSheet(
            "color: #D4D4D8; background-color: #1B1B21; border: 1px solid #2B2B34; "
            "border-radius: 4px; padding: 2px 6px; font-size: 7.2pt; font-weight: 700;"
        )
        hk_row.addWidget(self.lbl_hotkey_cap)
        hk_row.addStretch(1)

        esc_cap = QLabel("Esc")
        esc_cap.setStyleSheet(
            "color: #A1A1AA; background-color: #1B1B21; border: 1px solid #2B2B34; "
            "border-radius: 4px; padding: 2px 5px; font-size: 7.2pt; font-weight: 700;"
        )
        hk_row.addWidget(esc_cap)
        sb_lay.addLayout(hk_row)

        return sidebar

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 0: STUDIO (DICTATION & MODES)
    # ═══════════════════════════════════════════════════════════════════════
    def _build_studio_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("studioPage")
        page.setStyleSheet("QWidget#studioPage { background-color: #0A0A0C; }")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        # A) Top Command Bar
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(8)

        self.combo_studio_lang = FlatComboBox()
        self.combo_studio_lang.setMinimumHeight(34)
        self.combo_studio_lang.setMinimumWidth(116)
        for code, lbl in AVAILABLE_LANGUAGES:
            short_lang = lbl.split("(")[0].strip()
            self.combo_studio_lang.addItem(short_lang, code)
        self.combo_studio_lang.currentIndexChanged.connect(self._on_quick_lang_changed)
        cmd_row.addWidget(self.combo_studio_lang)

        self.combo_studio_model = FlatComboBox()
        self.combo_studio_model.setMinimumHeight(34)
        self.combo_studio_model.setMinimumWidth(134)
        for code, lbl in AVAILABLE_MODELS:
            short = lbl.split("—")[0].strip().replace("~", "")
            self.combo_studio_model.addItem(short, code)
        self.combo_studio_model.currentIndexChanged.connect(self._on_quick_model_changed)
        cmd_row.addWidget(self.combo_studio_model)

        self.btn_test_mic = QPushButton(f"  {self.i18n.t('btn_test_mic')}")
        self.btn_test_mic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_mic.setIcon(make_flat_icon("wave", "#D4D4D8", 13))
        self.btn_test_mic.setIconSize(QSize(13, 13))
        self.btn_test_mic.setMinimumHeight(36)
        self.btn_test_mic.clicked.connect(self._toggle_mic_test)
        cmd_row.addWidget(self.btn_test_mic)

        self.btn_drop_audio = QPushButton(f"  {self.i18n.t('btn_drop_audio')}")
        self.btn_drop_audio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_drop_audio.setIcon(make_flat_icon("upload", "#D4D4D8", 13))
        self.btn_drop_audio.setIconSize(QSize(13, 13))
        self.btn_drop_audio.setMinimumHeight(36)
        self.btn_drop_audio.clicked.connect(self._open_audio_file_dialog)
        cmd_row.addWidget(self.btn_drop_audio)

        cmd_row.addStretch(1)

        self.btn_dictate = QPushButton(f"  {self.i18n.t('btn_start_dictation')}")
        self.btn_dictate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dictate.setMinimumHeight(36)
        self.btn_dictate.setMinimumWidth(148)
        self._set_dictate_cta_style(recording=False)
        self.btn_dictate.clicked.connect(self._on_dictate_clicked)
        cmd_row.addWidget(self.btn_dictate)

        lay.addLayout(cmd_row)

        # B) Live Dictation Stage
        stage = QFrame()
        stage.setObjectName("stagePanel")
        st_lay = QVBoxLayout(stage)
        st_lay.setContentsMargins(16, 13, 16, 14)
        st_lay.setSpacing(10)

        # Stage header row
        st_hdr = QHBoxLayout()
        st_hdr.setSpacing(8)

        self.lbl_stage_title = QLabel(self.i18n.t("stage_title"))
        self.lbl_stage_title.setStyleSheet(
            "color: #71717A; font-size: 7.4pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        st_hdr.addWidget(self.lbl_stage_title)

        self.lbl_stage_pill = QLabel("● Ready")
        self.lbl_stage_pill.setStyleSheet(
            "color: #10B981; background-color: #0D231B; border: 1px solid #174131; "
            "border-radius: 5px; padding: 2px 8px; font-size: 7.5pt; font-weight: 700;"
        )
        st_hdr.addWidget(self.lbl_stage_pill)

        self.lbl_target_badge = QLabel("App-Aware · Ready")
        self.lbl_target_badge.setStyleSheet(
            "color: #C4B5FD; background-color: #1C162E; border: 1px solid #352759; "
            "border-radius: 5px; padding: 2px 8px; font-size: 7.4pt; font-weight: 600;"
        )
        st_hdr.addWidget(self.lbl_target_badge)

        st_hdr.addStretch(1)

        # Latency stage chips (VAD · STT · LLM · Paste)
        self._stage_chips: Dict[str, QLabel] = {}
        for key, init_txt in (
            ("vad", "VAD · ON"),
            ("stt", "STT · —"),
            ("llm", "LLM · OFF"),
            ("paste", "PASTE · —"),
        ):
            chip = QLabel(init_txt)
            chip.setStyleSheet(
                "color: #A1A1AA; background-color: #18181D; border: 1px solid #26262E; "
                "border-radius: 4px; padding: 2px 6px; font-size: 7.1pt; font-weight: 600;"
            )
            self._stage_chips[key] = chip
            st_hdr.addWidget(chip)

        st_lay.addLayout(st_hdr)

        # 24-bar Rolling Live Waveform
        self.waveform = LiveWaveformBar(bar_count=24)
        self.waveform.reset_idle()
        st_lay.addWidget(self.waveform)

        # Raw vs Refined Scratchpad Split
        split_row = QHBoxLayout()
        split_row.setSpacing(10)

        raw_box = QFrame()
        raw_box.setStyleSheet(
            "QFrame { background-color: #0D0D10; border: 1px solid #202027; border-radius: 8px; }"
        )
        raw_lay = QVBoxLayout(raw_box)
        raw_lay.setContentsMargins(11, 9, 11, 9)
        raw_lay.setSpacing(5)
        self.lbl_raw_hdr = QLabel(self.i18n.t("lbl_raw_transcript"))
        self.lbl_raw_hdr.setStyleSheet(
            "color: #71717A; font-size: 7.1pt; font-weight: 700; letter-spacing: 0.6px; border: none;"
        )
        raw_lay.addWidget(self.lbl_raw_hdr)
        self.txt_raw_stage = QPlainTextEdit()
        self.txt_raw_stage.setReadOnly(True)
        self.txt_raw_stage.setPlaceholderText(self.i18n.t("stage_empty_raw"))
        self.txt_raw_stage.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; color: #A1A1AA; "
            "font-size: 9pt; padding: 0px; }"
        )
        raw_lay.addWidget(self.txt_raw_stage, stretch=1)
        split_row.addWidget(raw_box, stretch=1)

        ref_box = QFrame()
        ref_box.setStyleSheet(
            "QFrame { background-color: #0F0F14; border: 1px solid #2D2645; border-radius: 8px; }"
        )
        ref_lay = QVBoxLayout(ref_box)
        ref_lay.setContentsMargins(11, 9, 11, 9)
        ref_lay.setSpacing(5)

        ref_hdr = QHBoxLayout()
        self.lbl_ref_hdr = QLabel(self.i18n.t("lbl_refined_output"))
        self.lbl_ref_hdr.setStyleSheet(
            "color: #A78BFA; font-size: 7.1pt; font-weight: 700; letter-spacing: 0.6px; border: none;"
        )
        ref_hdr.addWidget(self.lbl_ref_hdr)
        ref_hdr.addStretch(1)
        self.lbl_wpm_pill = QLabel("— WPM")
        self.lbl_wpm_pill.setStyleSheet(
            "color: #10B981; font-size: 7.2pt; font-weight: 700; border: none;"
        )
        ref_hdr.addWidget(self.lbl_wpm_pill)
        ref_lay.addLayout(ref_hdr)

        self.txt_refined_stage = QPlainTextEdit()
        self.txt_refined_stage.setPlaceholderText(self.i18n.t("stage_empty_refined"))
        self.txt_refined_stage.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; color: #FAFAFA; "
            "font-size: 9.4pt; font-weight: 500; padding: 0px; }"
        )
        ref_lay.addWidget(self.txt_refined_stage, stretch=1)
        split_row.addWidget(ref_box, stretch=1)

        st_lay.addLayout(split_row, stretch=1)

        # Stage Footer Actions
        st_foot = QHBoxLayout()
        st_foot.setSpacing(7)
        self.lbl_drop_hint = QLabel(self.i18n.t("stage_drop_hint"))
        self.lbl_drop_hint.setStyleSheet("color: #71717A; font-size: 7.6pt;")
        st_foot.addWidget(self.lbl_drop_hint, stretch=1)

        self.btn_stage_copy = QPushButton(f"  {self.i18n.t('btn_copy')}")
        self.btn_stage_copy.setIcon(make_flat_icon("copy", "#D4D4D8", 12))
        self.btn_stage_copy.setIconSize(QSize(12, 12))
        self.btn_stage_copy.clicked.connect(self._copy_stage_text)
        st_foot.addWidget(self.btn_stage_copy)

        self.btn_stage_repaste = QPushButton(f"  {self.i18n.t('btn_repaste')}")
        self.btn_stage_repaste.setIcon(make_flat_icon("paste", "#D4D4D8", 12))
        self.btn_stage_repaste.setIconSize(QSize(12, 12))
        self.btn_stage_repaste.clicked.connect(self._repaste_stage_text)
        st_foot.addWidget(self.btn_stage_repaste)

        self.btn_stage_clear = QPushButton(self.i18n.t("btn_clear"))
        self.btn_stage_clear.clicked.connect(self._clear_stage_text)
        st_foot.addWidget(self.btn_stage_clear)
        st_lay.addLayout(st_foot)

        lay.addWidget(stage, stretch=1)

        # C) Bottom Control Deck (Quick Mode Pills + Privacy/Routing Switches)
        deck_row = QHBoxLayout()
        deck_row.setSpacing(10)

        modes_card = QFrame()
        modes_card.setObjectName("studioPanel")
        m_lay = QVBoxLayout(modes_card)
        m_lay.setContentsMargins(14, 11, 14, 12)
        m_lay.setSpacing(8)

        self.lbl_mode_hdr = QLabel(self.i18n.t("lbl_mode_pills"))
        self.lbl_mode_hdr.setStyleSheet(
            "color: #71717A; font-size: 7.2pt; font-weight: 700; letter-spacing: 0.6px;"
        )
        m_lay.addWidget(self.lbl_mode_hdr)

        pills_grid = QGridLayout()
        pills_grid.setSpacing(6)
        for idx, (mode_id, i18n_key) in enumerate(MODE_PILLS):
            btn = QPushButton(self.i18n.t(i18n_key))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.setFixedHeight(29)
            btn.clicked.connect(lambda _c=False, m=mode_id: self._select_quick_mode(m))
            self._mode_buttons[mode_id] = btn
            r = idx // 4
            c = idx % 4
            pills_grid.addWidget(btn, r, c)
        m_lay.addLayout(pills_grid)
        deck_row.addWidget(modes_card, stretch=6)

        toggles_card = QFrame()
        toggles_card.setObjectName("studioPanel")
        t_lay = QVBoxLayout(toggles_card)
        t_lay.setContentsMargins(14, 11, 14, 12)
        t_lay.setSpacing(8)

        self.lbl_toggles_hdr = QLabel(self.i18n.t("lbl_toggles"))
        self.lbl_toggles_hdr.setStyleSheet(
            "color: #71717A; font-size: 7.2pt; font-weight: 700; letter-spacing: 0.6px;"
        )
        t_lay.addWidget(self.lbl_toggles_hdr)

        sw_grid = QGridLayout()
        sw_grid.setSpacing(6)
        self.sw_auto_paste = FlatSwitch(self.i18n.t("sw_auto_paste"), accent_hex=ACCENT_VIOLET)
        self.sw_app_aware = FlatSwitch(self.i18n.t("sw_app_aware"), accent_hex=ACCENT_VIOLET)
        self.sw_voice_cmds = FlatSwitch(self.i18n.t("sw_voice_cmds"), accent_hex=ACCENT_VIOLET)
        self.sw_offline_lock = FlatSwitch(self.i18n.t("sw_offline_lock"), accent_hex=ACCENT_EMERALD)

        for sw in (self.sw_auto_paste, self.sw_app_aware, self.sw_voice_cmds, self.sw_offline_lock):
            sw.toggled.connect(self._on_quick_switches_changed)

        sw_grid.addWidget(self.sw_auto_paste, 0, 0)
        sw_grid.addWidget(self.sw_app_aware, 0, 1)
        sw_grid.addWidget(self.sw_voice_cmds, 1, 0)
        sw_grid.addWidget(self.sw_offline_lock, 1, 1)
        t_lay.addLayout(sw_grid)
        deck_row.addWidget(toggles_card, stretch=5)

        lay.addLayout(deck_row)
        return page

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 1: HISTORY & PERSONAL DICTIONARY / SNIPPETS
    # ═══════════════════════════════════════════════════════════════════════
    def _build_history_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background-color: #0A0A0C;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        # Top 4 KPI Strip
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.kpi_dictations = TelemetryCard(
            self.i18n.t("kpi_dictations"), "SQLITE", "0", "Local encrypted disk", ACCENT_VIOLET, 40
        )
        self.kpi_words = TelemetryCard(
            self.i18n.t("kpi_words"), "TOTAL", "0", "40 WPM baseline", ACCENT_EMERALD, 55
        )
        self.kpi_saved = TelemetryCard(
            self.i18n.t("kpi_saved"), "ESTIMATED", "0.0 min", "vs manual typing", ACCENT_VIOLET, 48
        )
        self.kpi_latency = TelemetryCard(
            self.i18n.t("kpi_latency"), "WHISPER", "0.00s", "Average STT time", ACCENT_AMBER, 25
        )
        for card in (self.kpi_dictations, self.kpi_words, self.kpi_saved, self.kpi_latency):
            kpi_row.addWidget(card)
        lay.addLayout(kpi_row)

        # Search + Mode Filter + Export Bar
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.edit_history_search = QLineEdit()
        self.edit_history_search.setPlaceholderText(self.i18n.t("search_placeholder"))
        self.edit_history_search.setMinimumHeight(34)
        self.edit_history_search.textChanged.connect(lambda _t: self._search_timer.start())
        bar.addWidget(self.edit_history_search, stretch=1)

        self.combo_history_mode = FlatComboBox()
        self.combo_history_mode.setMinimumHeight(34)
        self.combo_history_mode.setMinimumWidth(120)
        self.combo_history_mode.addItem(self.i18n.t("filter_all_modes"), "all")
        for m_id, m_key in MODE_PILLS:
            self.combo_history_mode.addItem(self.i18n.t(m_key), m_id)
        self.combo_history_mode.currentIndexChanged.connect(lambda _i: self.refresh_history())
        bar.addWidget(self.combo_history_mode)

        self.btn_pinned_filter = QPushButton(f"  {self.i18n.t('btn_pin')}")
        self.btn_pinned_filter.setCheckable(True)
        self.btn_pinned_filter.setIcon(make_flat_icon("pin", "#D4D4D8", 12))
        self.btn_pinned_filter.setMinimumHeight(34)
        self.btn_pinned_filter.toggled.connect(self._on_pinned_filter_toggled)
        bar.addWidget(self.btn_pinned_filter)

        self.btn_export_history = QPushButton(f"  {self.i18n.t('btn_export')}")
        self.btn_export_history.setIcon(make_flat_icon("export", "#D4D4D8", 12))
        self.btn_export_history.setMinimumHeight(34)
        export_menu = QMenu(self)
        for label, fmt in (
            ("Markdown (.md)", "md"),
            ("CSV Spreadsheet (.csv)", "csv"),
            ("Plain Text (.txt)", "txt"),
            ("JSON Data (.json)", "json"),
        ):
            act = export_menu.addAction(label)
            act.triggered.connect(lambda _c=False, f=fmt: self._export_history(f))
        self.btn_export_history.setMenu(export_menu)
        bar.addWidget(self.btn_export_history)

        self.btn_clear_history = QPushButton(self.i18n.t("btn_clear"))
        self.btn_clear_history.setMinimumHeight(34)
        self.btn_clear_history.clicked.connect(self._clear_all_history)
        bar.addWidget(self.btn_clear_history)
        lay.addLayout(bar)

        # Main Split: History Cards (left 62%) + Personal Dictionary & Snippets (right 38%)
        split = QHBoxLayout()
        split.setSpacing(12)

        self.list_history = QListWidget()
        self.list_history.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list_history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_history.setResizeMode(QListWidget.ResizeMode.Adjust)
        split.addWidget(self.list_history, stretch=62)

        dict_card = QFrame()
        dict_card.setObjectName("studioPanel")
        d_lay = QVBoxLayout(dict_card)
        d_lay.setContentsMargins(13, 12, 13, 12)
        d_lay.setSpacing(8)

        self.lbl_dict_title = QLabel(self.i18n.t("dict_panel_title"))
        self.lbl_dict_title.setStyleSheet(
            "color: #A78BFA; font-size: 7.3pt; font-weight: 700; letter-spacing: 0.6px;"
        )
        d_lay.addWidget(self.lbl_dict_title)

        self.lbl_vocab = QLabel(self.i18n.t("dict_vocab_label"))
        self.lbl_vocab.setStyleSheet("color: #A1A1AA; font-size: 7.8pt; font-weight: 600;")
        d_lay.addWidget(self.lbl_vocab)

        self.edit_vocab = QLineEdit()
        self.edit_vocab.setPlaceholderText(self.i18n.t("dict_vocab_placeholder"))
        d_lay.addWidget(self.edit_vocab)

        self.lbl_snippets = QLabel(self.i18n.t("dict_snippets_label"))
        self.lbl_snippets.setStyleSheet("color: #A1A1AA; font-size: 7.8pt; font-weight: 600;")
        d_lay.addWidget(self.lbl_snippets)

        self.edit_snippets = QPlainTextEdit()
        self.edit_snippets.setPlaceholderText(
            "lgtm -> Looks good to me!\n"
            "c++ -> C++\n"
            "today date -> {{iso_date}}\n"
            "imzam -> Saygılarımla, Andaç"
        )
        d_lay.addWidget(self.edit_snippets, stretch=1)

        self.lbl_snippets_hint = QLabel(self.i18n.t("dict_snippets_hint"))
        self.lbl_snippets_hint.setStyleSheet("color: #71717A; font-size: 7.3pt;")
        d_lay.addWidget(self.lbl_snippets_hint)

        # Starter Pack Buttons
        packs_row = QHBoxLayout()
        packs_row.setSpacing(5)
        for pack_id, key in (
            ("developer", "dict_pack_dev"),
            ("business_en", "dict_pack_biz_en"),
            ("business_tr", "dict_pack_biz_tr"),
        ):
            pbtn = QPushButton(self.i18n.t(key))
            pbtn.setStyleSheet(
                "QPushButton { padding: 4px 7px; font-size: 7.6pt; background-color: #18181F; "
                "border: 1px solid #2A2A35; color: #C4B5FD; }"
                "QPushButton:hover { background-color: #241F36; border-color: #8B5CF6; }"
            )
            pbtn.clicked.connect(lambda _c=False, pid=pack_id: self._install_starter_pack(pid))
            packs_row.addWidget(pbtn)
        d_lay.addLayout(packs_row)

        self.btn_save_dict = QPushButton(self.i18n.t("btn_save_settings"))
        self.btn_save_dict.setStyleSheet(
            "QPushButton { background-color: #FAFAFA; color: #09090B; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 700; }"
            "QPushButton:hover { background-color: #E4E4E7; }"
        )
        self.btn_save_dict.clicked.connect(self._save_dictionary_panel)
        d_lay.addWidget(self.btn_save_dict)

        split.addWidget(dict_card, stretch=38)
        lay.addLayout(split, stretch=1)
        return page

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 2: SETTINGS & HARDWARE TELEMETRY
    # ═══════════════════════════════════════════════════════════════════════
    def _build_settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setStyleSheet("background-color: #0A0A0C;")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(20, 16, 20, 20)
        lay.setSpacing(12)

        # Hardware Summary Header Badge
        hw = self.controller.hw_profile
        tuning = self.controller.tuning
        self.lbl_hw_summary = QLabel(format_hardware_summary(hw, tuning, lang=self.i18n.lang))
        self.lbl_hw_summary.setStyleSheet(
            "color: #A1A1AA; background-color: #141417; border: 1px solid #24242A; "
            "border-radius: 8px; padding: 8px 12px; font-size: 8.2pt; font-weight: 600;"
        )
        lay.addWidget(self.lbl_hw_summary)

        # 4 TelemetryCard KPIs
        tele_row = QHBoxLayout()
        tele_row.setSpacing(10)
        self.tele_engine = TelemetryCard(
            self.i18n.t("tele_engine"),
            f"{tuning.whisper_threads} THREADS",
            self.controller.transcriber.active_compute_type.upper(),
            "faster-whisper + Silero VAD",
            ACCENT_VIOLET,
            72,
        )
        self.tele_vram = TelemetryCard(
            self.i18n.t("tele_vram"),
            "100% CPU",
            "0 MB",
            "Zero GPU contention",
            ACCENT_EMERALD,
            10,
        )
        self.tele_model = TelemetryCard(
            self.i18n.t("tele_model"),
            "OFFLINE",
            self.controller.config.model_size,
            "Cached" if is_model_cached(self.controller.config.model_size) else "On-demand",
            ACCENT_VIOLET,
            60,
        )
        self.tele_platform = TelemetryCard(
            self.i18n.t("tele_platform"),
            hw.arch.upper(),
            hw.os_display_label,
            f"{hw.physical_cores}C / {hw.logical_cores}T",
            ACCENT_AMBER,
            65,
        )
        for card in (self.tele_engine, self.tele_vram, self.tele_model, self.tele_platform):
            tele_row.addWidget(card)
        lay.addLayout(tele_row)

        # 2x2 Settings Panels Grid
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Panel 1: Audio & Microphone
        p_audio = self._make_section_card(self.i18n.t("settings_audio_title"))
        pa = p_audio.layout()
        assert isinstance(pa, QVBoxLayout)

        self.combo_mic = FlatComboBox(on_before_popup=self._populate_mic_devices)
        self._populate_mic_devices()
        pa.addWidget(self._field_row(self.i18n.t("lbl_mic_device"), self.combo_mic))

        vu_row = QHBoxLayout()
        self.bar_mic_vu = QProgressBar()
        self.bar_mic_vu.setRange(0, 100)
        self.bar_mic_vu.setValue(0)
        self.bar_mic_vu.setTextVisible(False)
        self.bar_mic_vu.setFixedHeight(8)
        self.bar_mic_vu.setStyleSheet(
            "QProgressBar { background-color: #1A1A20; border: 1px solid #26262E; border-radius: 4px; }"
            "QProgressBar::chunk { background-color: #10B981; border-radius: 3px; }"
        )
        vu_row.addWidget(self.bar_mic_vu, stretch=1)
        self.btn_settings_mic_test = QPushButton(self.i18n.t("btn_test_mic"))
        self.btn_settings_mic_test.clicked.connect(self._toggle_mic_test)
        vu_row.addWidget(self.btn_settings_mic_test)
        pa.addLayout(vu_row)

        lim_row = QHBoxLayout()
        self.spin_silence_stop = QDoubleSpinBox()
        self.spin_silence_stop.setRange(0.0, 15.0)
        self.spin_silence_stop.setSingleStep(0.5)
        self.spin_silence_stop.setSuffix(" s")
        self.spin_silence_stop.setSpecialValueText("Off")
        lim_row.addWidget(self._field_row(self.i18n.t("lbl_silence_stop"), self.spin_silence_stop))

        self.spin_max_rec = QSpinBox()
        self.spin_max_rec.setRange(15, 1800)
        self.spin_max_rec.setSuffix(" s")
        lim_row.addWidget(self._field_row(self.i18n.t("lbl_max_duration"), self.spin_max_rec))
        pa.addLayout(lim_row)

        self.sw_sound_cues = FlatSwitch(self.i18n.t("sw_sound_cues"), accent_hex=ACCENT_VIOLET)
        pa.addWidget(self.sw_sound_cues)
        grid.addWidget(p_audio, 0, 0)

        # Panel 2: Hotkeys & OS Permissions
        p_hk = self._make_section_card(self.i18n.t("settings_hotkey_title"))
        ph = p_hk.layout()
        assert isinstance(ph, QVBoxLayout)

        self.combo_hk_mode = FlatComboBox()
        for val, lbl in HOTKEY_MODES:
            self.combo_hk_mode.addItem(lbl, val)
        ph.addWidget(self._field_row(self.i18n.t("lbl_hotkey_mode"), self.combo_hk_mode))

        hk_inputs = QHBoxLayout()
        self.edit_toggle_hk = QLineEdit()
        self.edit_ptt_hk = QLineEdit()
        hk_inputs.addWidget(self._field_row(self.i18n.t("lbl_toggle_hk"), self.edit_toggle_hk))
        hk_inputs.addWidget(self._field_row(self.i18n.t("lbl_ptt_hk"), self.edit_ptt_hk))
        ph.addLayout(hk_inputs)

        presets = QHBoxLayout()
        preset_items = (
            [("⌥ + Space", "toggle", "alt+space"), ("Right ⌥ (PTT)", "push_to_talk", "alt_r")]
            if sys.platform == "darwin"
            else [
                ("Ctrl+Alt+Space", "toggle", "ctrl+alt+space"),
                ("Right Ctrl (PTT)", "push_to_talk", "ctrl_r"),
                ("F9 (PTT)", "push_to_talk", "f9"),
            ]
        )
        for lbl, mode, hk in preset_items:
            b = QPushButton(lbl)
            b.setStyleSheet("QPushButton { padding: 4px 8px; font-size: 7.7pt; }")
            b.clicked.connect(lambda _c=False, m=mode, k=hk: self._apply_hotkey_preset(m, k))
            presets.addWidget(b)
        ph.addLayout(presets)

        self.combo_overlay_pos = FlatComboBox()
        self.combo_overlay_pos.addItem("Bottom Center", "bottom_center")
        self.combo_overlay_pos.addItem("Top Center", "top_center")
        ph.addWidget(self._field_row(self.i18n.t("lbl_overlay_pos"), self.combo_overlay_pos))

        self.sw_restore_clip = FlatSwitch(self.i18n.t("sw_restore_clip"), accent_hex=ACCENT_VIOLET)
        ph.addWidget(self.sw_restore_clip)

        tcc_ok = check_accessibility_permission()
        self.lbl_tcc_status = QLabel(
            self.i18n.t("lbl_accessibility_ok") if tcc_ok else self.i18n.t("lbl_accessibility_warn")
        )
        self.lbl_tcc_status.setWordWrap(True)
        self.lbl_tcc_status.setStyleSheet(
            f"color: {'#10B981' if tcc_ok else '#F59E0B'}; font-size: 7.6pt; font-weight: 600;"
        )
        ph.addWidget(self.lbl_tcc_status)
        grid.addWidget(p_hk, 0, 1)

        # Panel 3: Whisper Model Manager
        p_mod = self._make_section_card(self.i18n.t("settings_model_title"))
        pm = p_mod.layout()
        assert isinstance(pm, QVBoxLayout)

        self.combo_settings_model = FlatComboBox()
        for val, lbl in AVAILABLE_MODELS:
            self.combo_settings_model.addItem(lbl, val)
        self.combo_settings_model.currentIndexChanged.connect(self._refresh_model_cache_label)
        pm.addWidget(self._field_row(self.i18n.t("lbl_model_select"), self.combo_settings_model))

        self.lbl_model_cache = QLabel("")
        self.lbl_model_cache.setStyleSheet("color: #10B981; font-size: 7.7pt; font-weight: 600;")
        pm.addWidget(self.lbl_model_cache)

        prof_row = QHBoxLayout()
        self.combo_perf_profile = FlatComboBox()
        for val, lbl in (
            (PROFILE_AUTO, "Auto (Recommended)"),
            (PROFILE_ECO, "Eco (Low CPU)"),
            (PROFILE_BALANCED, "Balanced"),
            (PROFILE_PERFORMANCE, "Performance (Max Speed)"),
        ):
            self.combo_perf_profile.addItem(lbl, val)
        prof_row.addWidget(self._field_row(self.i18n.t("lbl_perf_profile"), self.combo_perf_profile))

        self.spin_beam = QSpinBox()
        self.spin_beam.setRange(1, 10)
        prof_row.addWidget(self._field_row("Beam Size", self.spin_beam))
        pm.addLayout(prof_row)

        self.sw_vad = FlatSwitch("Silero VAD Silence Filter", accent_hex=ACCENT_EMERALD)
        pm.addWidget(self.sw_vad)
        grid.addWidget(p_mod, 1, 0)

        # Panel 4: Local / BYOK LLM Refinement
        p_llm = self._make_section_card(self.i18n.t("settings_llm_title"))
        pl = p_llm.layout()
        assert isinstance(pl, QVBoxLayout)

        self.sw_llm_enabled = FlatSwitch(self.i18n.t("lbl_llm_enable"), accent_hex=ACCENT_VIOLET)
        pl.addWidget(self.sw_llm_enabled)

        self.combo_llm_backend = FlatComboBox()
        for val, lbl in LLM_BACKENDS:
            self.combo_llm_backend.addItem(lbl, val)
        pl.addWidget(self._field_row(self.i18n.t("lbl_llm_backend"), self.combo_llm_backend))

        self.edit_llm_url = QLineEdit()
        self.edit_llm_url.setPlaceholderText("http://localhost:11434")
        pl.addWidget(self._field_row(self.i18n.t("lbl_llm_url"), self.edit_llm_url))

        llm_mod_row = QHBoxLayout()
        self.combo_llm_model = FlatComboBox()
        self.combo_llm_model.setEditable(True)
        llm_mod_row.addWidget(self.combo_llm_model, stretch=1)
        self.btn_test_llm = QPushButton(self.i18n.t("btn_test_llm"))
        self.btn_test_llm.clicked.connect(self._test_llm_async)
        llm_mod_row.addWidget(self.btn_test_llm)
        pl.addLayout(llm_mod_row)

        self.edit_llm_apikey = QLineEdit()
        self.edit_llm_apikey.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_llm_apikey.setPlaceholderText("Optional (only for external OpenAI-compatible APIs)")
        pl.addWidget(self._field_row(self.i18n.t("lbl_llm_apikey"), self.edit_llm_apikey))

        self.lbl_llm_status = QLabel("")
        self.lbl_llm_status.setStyleSheet("color: #71717A; font-size: 7.6pt;")
        pl.addWidget(self.lbl_llm_status)
        grid.addWidget(p_llm, 1, 1)

        lay.addLayout(grid)

        # Panel 5: Interface, System, Updater & Benchmark
        p_sys = self._make_section_card(self.i18n.t("settings_app_title"))
        ps = p_sys.layout()
        assert isinstance(ps, QVBoxLayout)

        top_sys = QHBoxLayout()
        self.combo_ui_lang = FlatComboBox()
        self.combo_ui_lang.addItem("English (EN)", "en")
        self.combo_ui_lang.addItem("Türkçe (TR)", "tr")
        top_sys.addWidget(self._field_row(self.i18n.t("lbl_ui_language"), self.combo_ui_lang))

        self.sw_autostart = FlatSwitch(self.i18n.t("sw_autostart"), accent_hex=ACCENT_VIOLET)
        self.sw_min_tray = FlatSwitch(self.i18n.t("sw_min_tray"), accent_hex=ACCENT_VIOLET)
        self.sw_auto_update = FlatSwitch(self.i18n.t("sw_auto_update"), accent_hex=ACCENT_VIOLET)

        sw_col = QVBoxLayout()
        sw_col.addWidget(self.sw_autostart)
        sw_col.addWidget(self.sw_min_tray)
        sw_col.addWidget(self.sw_auto_update)
        top_sys.addLayout(sw_col, stretch=1)
        ps.addLayout(top_sys)

        act_row = QHBoxLayout()
        act_row.setSpacing(8)
        self.btn_check_updates = QPushButton(f"  {self.i18n.t('btn_check_updates')}")
        self.btn_check_updates.setIcon(make_flat_icon("refresh", "#D4D4D8", 12))
        self.btn_check_updates.clicked.connect(lambda: self.check_for_updates_async(silent=False))
        act_row.addWidget(self.btn_check_updates)

        self.btn_run_bench = QPushButton(f"  {self.i18n.t('btn_benchmark')}")
        self.btn_run_bench.setIcon(make_flat_icon("gauge", "#D4D4D8", 12))
        self.btn_run_bench.clicked.connect(self._run_quick_benchmark)
        act_row.addWidget(self.btn_run_bench)

        act_row.addStretch(1)

        self.btn_save_settings = QPushButton(self.i18n.t("btn_save_settings"))
        self.btn_save_settings.setMinimumHeight(34)
        self.btn_save_settings.setStyleSheet(
            "QPushButton { background-color: #FAFAFA; color: #09090B; border: none; "
            "border-radius: 7px; padding: 6px 18px; font-weight: 700; }"
            "QPushButton:hover { background-color: #E4E4E7; }"
        )
        self.btn_save_settings.clicked.connect(self._save_settings_from_ui)
        act_row.addWidget(self.btn_save_settings)
        ps.addLayout(act_row)

        self.lbl_sys_feedback = QLabel("")
        self.lbl_sys_feedback.setStyleSheet("color: #A1A1AA; font-size: 7.8pt;")
        ps.addWidget(self.lbl_sys_feedback)

        lay.addWidget(p_sys)
        lay.addStretch(1)

        scroll.setWidget(content)
        return scroll

    @staticmethod
    def _make_section_card(title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("studioPanel")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lbl = QLabel(title)
        lbl.setStyleSheet(
            "color: #A78BFA; font-size: 7.3pt; font-weight: 700; letter-spacing: 0.6px;"
        )
        lay.addWidget(lbl)
        return card

    @staticmethod
    def _field_row(label: str, widget: QWidget) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #A1A1AA; font-size: 7.6pt; font-weight: 600;")
        lay.addWidget(lbl)
        lay.addWidget(widget)
        return wrap

    # ═══════════════════════════════════════════════════════════════════════
    # CONTROLLER WIRING & LIVE STATE UPDATES
    # ═══════════════════════════════════════════════════════════════════════
    def _connect_controller_signals(self) -> None:
        self.controller.state_changed.connect(self.on_state_changed)
        self.controller.audio_level.connect(self.on_audio_level)
        self.controller.dictation_completed.connect(self.on_dictation_completed)
        self.controller.model_ready.connect(self.on_model_ready)
        self.controller.active_context_changed.connect(self.on_active_context_changed)
        if hasattr(self.controller, "recording_starting"):
            self.controller.recording_starting.connect(self._stop_mic_test_for_dictation)

    def switch_tab(self, index: int) -> None:
        self._active_tab = max(0, min(2, int(index)))
        self.stack.setCurrentIndex(self._active_tab)
        for idx, btn in enumerate((self.btn_nav_studio, self.btn_nav_history, self.btn_nav_settings)):
            btn.set_active(idx == self._active_tab)
        if self._active_tab == 1:
            self.refresh_history()
        elif self._active_tab == 2:
            self._refresh_model_cache_label()

    def _set_dictate_cta_style(self, recording: bool) -> None:
        if recording:
            self.btn_dictate.setText(f"  {self.i18n.t('btn_stop_dictation')}")
            self.btn_dictate.setIcon(make_flat_icon("stop", "#FFFFFF", 12))
            self.btn_dictate.setIconSize(QSize(12, 12))
            self.btn_dictate.setStyleSheet(
                "QPushButton { background-color: #E11D48; color: #FFFFFF; border: none; "
                "border-radius: 8px; padding: 0 16px; font-size: 8.8pt; font-weight: 700; }"
                "QPushButton:hover { background-color: #BE123C; }"
            )
        else:
            self.btn_dictate.setText(f"  {self.i18n.t('btn_start_dictation')}")
            self.btn_dictate.setIcon(make_flat_icon("mic", "#09090B", 13))
            self.btn_dictate.setIconSize(QSize(13, 13))
            self.btn_dictate.setStyleSheet(
                "QPushButton { background-color: #FAFAFA; color: #09090B; border: none; "
                "border-radius: 8px; padding: 0 16px; font-size: 8.8pt; font-weight: 700; }"
                "QPushButton:hover { background-color: #E4E4E7; }"
            )

    def _update_mode_pill_styles(self, active_mode: str) -> None:
        for mode_id, btn in self._mode_buttons.items():
            is_sel = mode_id == active_mode
            btn.blockSignals(True)
            btn.setChecked(is_sel)
            btn.blockSignals(False)
            if is_sel:
                btn.setStyleSheet(
                    "QPushButton { background-color: #241C3D; color: #FAFAFA; "
                    "border: 1px solid #8B5CF6; border-radius: 7px; padding: 4px 8px; "
                    "font-size: 8pt; font-weight: 700; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background-color: #18181E; color: #A1A1AA; "
                    "border: 1px solid #26262F; border-radius: 7px; padding: 4px 8px; "
                    "font-size: 8pt; font-weight: 600; }"
                    "QPushButton:hover { background-color: #21212A; color: #FAFAFA; border-color: #3E3E4C; }"
                )

    def on_state_changed(self, state: str, message: str) -> None:
        if state == AppState.RECORDING.value and self._mic_testing:
            self._stop_mic_test(reset_waveform=False)
        self.waveform.set_state(state)
        self.lbl_engine_status.setText(message)

        if state == AppState.RECORDING.value:
            self._set_dictate_cta_style(recording=True)
            self._sidebar_dot.setStyleSheet("background-color: #E11D48; border-radius: 3px; border: none;")
            self.btn_nav_studio.set_badge(self.i18n.t("badge_live"), kind="rec")
            self.lbl_stage_pill.setText(f"● {message}")
            self.lbl_stage_pill.setStyleSheet(
                "color: #FB7185; background-color: #2B1018; border: 1px solid #591C2E; "
                "border-radius: 5px; padding: 2px 8px; font-size: 7.5pt; font-weight: 700;"
            )
            self.engine_progress.setValue(100)
        elif state in (AppState.TRANSCRIBING.value, AppState.REFINING.value):
            self._set_dictate_cta_style(recording=False)
            self._sidebar_dot.setStyleSheet("background-color: #8B5CF6; border-radius: 3px; border: none;")
            self.btn_nav_studio.set_badge("AI", kind="loading")
            self.lbl_stage_pill.setText(f"● {message}")
            self.lbl_stage_pill.setStyleSheet(
                "color: #C4B5FD; background-color: #1C162E; border: 1px solid #352759; "
                "border-radius: 5px; padding: 2px 8px; font-size: 7.5pt; font-weight: 700;"
            )
        elif state == AppState.LOADING_MODEL.value:
            self._set_dictate_cta_style(recording=False)
            self._sidebar_dot.setStyleSheet("background-color: #F59E0B; border-radius: 3px; border: none;")
            self.btn_nav_studio.set_badge(self.i18n.t("badge_loading"), kind="loading")
            self.lbl_stage_pill.setText(f"● {message}")
            self.engine_progress.setValue(45)
        elif state == AppState.ERROR.value:
            self._set_dictate_cta_style(recording=False)
            self._sidebar_dot.setStyleSheet("background-color: #FB7185; border-radius: 3px; border: none;")
            self.lbl_stage_pill.setText(f"● {message}")
            self.lbl_stage_pill.setStyleSheet(
                "color: #FB7185; background-color: #2B1018; border: 1px solid #591C2E; "
                "border-radius: 5px; padding: 2px 8px; font-size: 7.5pt; font-weight: 700;"
            )
        else:
            self._set_dictate_cta_style(recording=False)
            self._sidebar_dot.setStyleSheet("background-color: #10B981; border-radius: 3px; border: none;")
            self.btn_nav_studio.set_badge(self.i18n.t("badge_ready"), kind="live")
            self.lbl_stage_pill.setText(f"● {message or self.i18n.t('status_ready')}")
            self.lbl_stage_pill.setStyleSheet(
                "color: #10B981; background-color: #0D231B; border: 1px solid #174131; "
                "border-radius: 5px; padding: 2px 8px; font-size: 7.5pt; font-weight: 700;"
            )
            self.engine_progress.setValue(100)

    def on_audio_level(self, level: float) -> None:
        self.waveform.push_level(level)
        self.bar_mic_vu.setValue(int(round(max(0.0, min(1.0, level)) * 100)))

    def on_active_context_changed(self, target_app: str, mode: str) -> None:
        mode_lbl = mode.replace("_", " ").title()
        if target_app:
            self.lbl_target_badge.setText(f"{target_app} → {mode_lbl}")
        else:
            self.lbl_target_badge.setText(f"Mode: {mode_lbl}")
        self._update_mode_pill_styles(mode)

    def on_model_ready(self, model_size: str) -> None:
        ctype = self.controller.transcriber.active_compute_type.upper()
        self.lbl_engine_meta.setText(f"{ctype} ({model_size}) · 0 MB VRAM")
        self.tele_engine.set_metric(
            ctype,
            f"{model_size} · Silero VAD",
            f"{self.controller.transcriber.active_threads or self.controller.tuning.whisper_threads}T",
            78,
        )
        self.tele_model.set_metric(model_size, self.i18n.t("lbl_model_cached"), "READY", 100)
        self._refresh_model_cache_label()

    def on_dictation_completed(self, outcome: DictationOutcome) -> None:
        """Populate the Live Dictation Stage with real transcription metrics and text."""
        self.txt_raw_stage.setPlainText(outcome.raw_text)
        self.txt_refined_stage.setPlainText(outcome.final_text)
        self.lbl_wpm_pill.setText(f"{outcome.wpm} WPM" if outcome.wpm > 0 else "— WPM")
        self._stage_chips["vad"].setText("VAD · ON" if self.controller.config.vad_filter else "VAD · OFF")
        self._stage_chips["stt"].setText(f"STT · {int(round(outcome.stt_sec * 1000))}ms")
        self._stage_chips["llm"].setText(
            f"LLM · {int(round(outcome.llm_sec * 1000))}ms" if outcome.used_llm else "LLM · OFF"
        )
        self._stage_chips["paste"].setText(
            f"PASTE · {int(round(outcome.paste_sec * 1000))}ms" if outcome.pasted else "CLIPBOARD"
        )
        self.on_active_context_changed(outcome.target_app, outcome.mode)
        self.refresh_history()

    # ═══════════════════════════════════════════════════════════════════════
    # ACTIONS & HANDLERS
    # ═══════════════════════════════════════════════════════════════════════
    @staticmethod
    def _select_combo_data(combo: FlatComboBox, value) -> None:
        combo.blockSignals(True)
        try:
            for i in range(combo.count()):
                if combo.itemData(i) == value:
                    combo.setCurrentIndex(i)
                    return
        finally:
            combo.blockSignals(False)

    def _populate_mic_devices(self) -> None:
        current = self.combo_mic.currentData() if hasattr(self, "combo_mic") else self.controller.config.input_device
        self.combo_mic.blockSignals(True)
        try:
            self.combo_mic.clear()
            self.combo_mic.addItem(self.i18n.t("lbl_mic_default"), None)
            for idx, name in list_input_devices():
                self.combo_mic.addItem(name, idx)
            self._select_combo_data(self.combo_mic, current)
        finally:
            self.combo_mic.blockSignals(False)

    def _sync_ui_from_config(self) -> None:
        cfg = self.controller.config
        self._select_combo_data(self.combo_studio_lang, cfg.language)
        self._select_combo_data(self.combo_studio_model, cfg.model_size)
        self._select_combo_data(self.combo_settings_model, cfg.model_size)
        self._select_combo_data(self.combo_mic, cfg.input_device)
        self._select_combo_data(self.combo_hk_mode, cfg.hotkey_mode)
        self._select_combo_data(self.combo_overlay_pos, cfg.overlay_position)
        self._select_combo_data(self.combo_perf_profile, cfg.performance_profile)
        self._select_combo_data(self.combo_llm_backend, cfg.llm_backend)
        self._select_combo_data(self.combo_ui_lang, cfg.ui_language)

        self.edit_toggle_hk.setText(cfg.toggle_hotkey)
        self.edit_ptt_hk.setText(cfg.ptt_hotkey)
        self.lbl_hotkey_cap.setText(format_hotkey_display(cfg.active_hotkey))
        self.spin_silence_stop.setValue(float(cfg.silence_auto_stop_sec))
        self.spin_max_rec.setValue(int(cfg.max_recording_sec))
        self.spin_beam.setValue(int(cfg.beam_size))

        for sw, val in (
            (self.sw_auto_paste, cfg.auto_paste),
            (self.sw_app_aware, cfg.app_aware_routing),
            (self.sw_voice_cmds, cfg.voice_commands_enabled),
            (self.sw_offline_lock, cfg.offline_only),
            (self.sw_sound_cues, cfg.sound_effects),
            (self.sw_restore_clip, cfg.restore_clipboard),
            (self.sw_vad, cfg.vad_filter),
            (self.sw_llm_enabled, cfg.ollama_enabled),
            (self.sw_autostart, cfg.launch_at_startup),
            (self.sw_min_tray, cfg.minimize_to_tray),
            (self.sw_auto_update, cfg.check_updates_on_startup),
        ):
            sw.blockSignals(True)
            sw.setChecked(bool(val))
            sw.blockSignals(False)

        self.edit_llm_url.setText(cfg.ollama_url)
        self.combo_llm_model.setCurrentText(cfg.ollama_model)
        self.edit_llm_apikey.setText(cfg.llm_api_key)

        self.edit_vocab.setText(", ".join(cfg.custom_vocabulary))
        self.edit_vocab.setCursorPosition(0)
        merged_rules = dict(cfg.snippets)
        merged_rules.update(cfg.replacements)
        self.edit_snippets.setPlainText(_format_rules_text(merged_rules))

        self._update_mode_pill_styles(cfg.effective_style)
        self._refresh_model_cache_label()
        self.lbl_engine_meta.setText(
            f"{cfg.compute_type.upper()} ({cfg.model_size}) · 0 MB VRAM"
        )

    def _refresh_model_cache_label(self) -> None:
        model = str(self.combo_settings_model.currentData() or self.controller.config.model_size)
        cached = is_model_cached(model)
        if cached:
            self.lbl_model_cache.setText(f"● {model}: {self.i18n.t('lbl_model_cached')}")
            self.lbl_model_cache.setStyleSheet("color: #10B981; font-size: 7.7pt; font-weight: 600;")
        else:
            self.lbl_model_cache.setText(f"○ {model}: {self.i18n.t('lbl_model_not_cached')}")
            self.lbl_model_cache.setStyleSheet("color: #A1A1AA; font-size: 7.7pt; font-weight: 600;")

    def _on_quick_lang_changed(self) -> None:
        lang = str(self.combo_studio_lang.currentData() or "auto")
        if lang != self.controller.config.language:
            new_cfg = replace(self.controller.config, language=lang)
            self.controller.apply_config(new_cfg, persist=True)
            self.config_applied.emit(new_cfg)

    def _on_quick_model_changed(self) -> None:
        model = str(self.combo_studio_model.currentData() or "small")
        if model != self.controller.config.model_size:
            new_cfg = replace(self.controller.config, model_size=model)
            self._select_combo_data(self.combo_settings_model, model)
            self.controller.apply_config(new_cfg, persist=True)
            self.tele_model.set_metric(model, self.i18n.t("lbl_model_not_cached"), "LOAD", 50)
            self.config_applied.emit(new_cfg)

    def _select_quick_mode(self, mode: str) -> None:
        self.controller.set_dictation_mode(mode, persist=True)
        self._update_mode_pill_styles(mode)
        self.config_applied.emit(self.controller.config)

    def _on_quick_switches_changed(self) -> None:
        new_cfg = replace(
            self.controller.config,
            auto_paste=self.sw_auto_paste.isChecked(),
            app_aware_routing=self.sw_app_aware.isChecked(),
            voice_commands_enabled=self.sw_voice_cmds.isChecked(),
            offline_only=self.sw_offline_lock.isChecked(),
        )
        self.controller.apply_config(new_cfg, persist=True)
        self.config_applied.emit(new_cfg)

    def _copy_stage_text(self) -> None:
        txt = self.txt_refined_stage.toPlainText().strip() or self.controller.last_text
        if not txt:
            return
        try:
            pyperclip.copy(txt)
            self.lbl_stage_pill.setText(f"● {self.i18n.t('status_copied_last')}")
        except Exception:
            pass

    def _repaste_stage_text(self) -> None:
        txt = self.txt_refined_stage.toPlainText().strip() or self.controller.last_text
        if txt:
            self.controller.injector.inject(txt)

    def _clear_stage_text(self) -> None:
        self.txt_raw_stage.clear()
        self.txt_refined_stage.clear()
        self.lbl_wpm_pill.setText("— WPM")
        self.waveform.reset_idle()

    def _on_dictate_clicked(self) -> None:
        if self._mic_testing:
            self._stop_mic_test(reset_waveform=False)
        self.controller.toggle_recording()

    def _stop_mic_test_for_dictation(self) -> None:
        if self._mic_testing:
            self._stop_mic_test(reset_waveform=False)

    def _toggle_mic_test(self) -> None:
        if self._mic_testing:
            self._stop_mic_test()
            return
        try:
            dev = self.combo_mic.currentData()
            rec = AudioRecorder(device=dev)
            rec.start()
            self._mic_test_recorder = rec
            self._mic_testing = True
            self.waveform.set_state("recording")
            self.btn_test_mic.setText(f"  {self.i18n.t('btn_stop_test')}")
            self.btn_settings_mic_test.setText(self.i18n.t("btn_stop_test"))
            self._mic_test_timer.start()
        except Exception as exc:
            self.lbl_stage_pill.setText(f"● {self.i18n.t('status_mic_error', err=exc)}")

    def _stop_mic_test(self, reset_waveform: bool = True) -> None:
        self._mic_test_timer.stop()
        if self._mic_test_recorder is not None:
            try:
                self._mic_test_recorder.cancel()
            except Exception:
                pass
            self._mic_test_recorder = None
        self._mic_testing = False
        if reset_waveform:
            self.waveform.set_state("idle")
            self.waveform.reset_idle()
        self.bar_mic_vu.setValue(0)
        self.btn_test_mic.setText(f"  {self.i18n.t('btn_test_mic')}")
        self.btn_settings_mic_test.setText(self.i18n.t("btn_test_mic"))

    def _poll_mic_test(self) -> None:
        if self._mic_test_recorder is None:
            return
        lvl = self._mic_test_recorder.get_latest_level()
        self.waveform.push_level(lvl)
        self.bar_mic_vu.setValue(int(round(lvl * 100)))

    def _open_audio_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.i18n.t("btn_drop_audio"),
            "",
            "Audio Files (*.wav *.mp3 *.m4a *.flac *.ogg *.webm);;All Files (*)",
        )
        if path:
            self.controller.transcribe_audio_file(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime and mime.hasUrls():
            for url in mime.urls():
                if Path(url.toLocalFile()).suffix.lower() in AUDIO_FILE_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if not mime or not mime.hasUrls():
            return
        for url in mime.urls():
            fpath = Path(url.toLocalFile())
            if fpath.suffix.lower() in AUDIO_FILE_EXTENSIONS:
                self.switch_tab(0)
                self.controller.transcribe_audio_file(fpath)
                event.acceptProposedAction()
                return

    # ═══════════════════════════════════════════════════════════════════════
    # HISTORY & SNIPPETS LOGIC
    # ═══════════════════════════════════════════════════════════════════════
    def _on_pinned_filter_toggled(self, checked: bool) -> None:
        self._pinned_only = checked
        self.refresh_history()

    def refresh_history(self) -> None:
        stats = self.history.get_stats()
        self.kpi_dictations.set_metric(
            f"{stats.total_dictations:,}",
            "100% local SQLite",
            "STORED",
            min(100, 15 + stats.total_dictations * 2),
        )
        self.kpi_words.set_metric(
            f"{stats.total_words:,}",
            f"{stats.total_audio_sec / 60.0:.1f} min spoken",
            "WORDS",
            min(100, 20 + stats.total_words // 25),
        )
        self.kpi_saved.set_metric(
            f"{stats.estimated_minutes_saved:.1f} min",
            "vs 40 WPM typing",
            "SAVED",
            min(100, 20 + int(stats.estimated_minutes_saved * 4)),
        )
        self.kpi_latency.set_metric(
            f"{stats.avg_inference_sec:.2f}s",
            "Whisper CPU INT8",
            "AVG",
            max(10, min(95, int(100 - stats.avg_inference_sec * 35))),
        )
        self.btn_nav_history.set_badge(str(stats.total_dictations), kind="muted")

        query = self.edit_history_search.text()
        mode_filter = str(self.combo_history_mode.currentData() or "all")
        self._history_entries = self.history.list_recent(
            limit=120,
            query=query,
            mode_filter=mode_filter,
            pinned_only=self._pinned_only,
        )
        self.list_history.clear()
        vp_w = self.list_history.viewport().width()
        card_w = max(360, vp_w - 14) if vp_w > 120 else 412

        for entry in self._history_entries:
            card = self._create_history_card(entry)
            card.setFixedWidth(card_w)
            card.adjustSize()
            hint = card.sizeHint()
            item = QListWidgetItem(self.list_history)
            item.setSizeHint(QSize(card_w, hint.height() + 4))
            self.list_history.addItem(item)
            self.list_history.setItemWidget(item, card)

    def _create_history_card(self, entry: HistoryEntry) -> QFrame:
        card = QFrame()
        border_col = "#4C3575" if entry.pinned else "#24242A"
        card.setStyleSheet(
            f"QFrame {{ background-color: #141418; border: 1px solid {border_col}; border-radius: 8px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(5)
        ts_short = entry.created_at[5:16] if len(entry.created_at) >= 16 else entry.created_at
        ts_lbl = QLabel(ts_short)
        ts_lbl.setStyleSheet("color: #71717A; font-size: 7.2pt; font-weight: 600; border: none;")
        meta_row.addWidget(ts_lbl)

        if entry.target_app:
            app_pill = QLabel(entry.target_app)
            app_pill.setStyleSheet(
                "color: #E4E4E7; background-color: #1D1D24; border: 1px solid #2C2C36; "
                "border-radius: 4px; padding: 1px 5px; font-size: 6.9pt; font-weight: 600;"
            )
            meta_row.addWidget(app_pill)

        mode_lbl = entry.mode.replace("_", " ").upper()
        if mode_lbl == "TRANSLATE EN":
            mode_lbl = "TR→EN"
        elif mode_lbl == "BULLET NOTES":
            mode_lbl = "NOTES"
        elif mode_lbl == "GIT COMMIT":
            mode_lbl = "GIT"
        mode_pill = QLabel(mode_lbl)
        mode_pill.setStyleSheet(
            "color: #C4B5FD; background-color: #1E1833; border: 1px solid #352759; "
            "border-radius: 4px; padding: 1px 5px; font-size: 6.9pt; font-weight: 700;"
        )
        meta_row.addWidget(mode_pill)

        perf_txt = f"{entry.inference_sec:.2f}s"
        if entry.wpm > 0:
            perf_txt += f" · {entry.wpm} WPM"
        if entry.used_llm:
            perf_txt += " · LLM"
        perf_lbl = QLabel(perf_txt)
        perf_lbl.setStyleSheet("color: #10B981; font-size: 7.1pt; font-weight: 600; border: none;")
        meta_row.addWidget(perf_lbl)
        meta_row.addStretch(1)

        btn_pin = QPushButton("★" if entry.pinned else "☆")
        btn_pin.setFixedSize(20, 20)
        btn_pin.setToolTip(self.i18n.t("btn_unpin" if entry.pinned else "btn_pin"))
        btn_pin.setStyleSheet(
            f"QPushButton {{ padding: 0; font-size: 9pt; color: {'#8B5CF6' if entry.pinned else '#71717A'}; "
            "background: transparent; border: none; }"
            "QPushButton:hover { color: #FAFAFA; }"
        )
        btn_pin.clicked.connect(lambda _c=False, eid=entry.id: self._toggle_pin_entry(eid))
        meta_row.addWidget(btn_pin)

        btn_copy = QPushButton("")
        btn_copy.setFixedSize(20, 20)
        btn_copy.setIcon(make_flat_icon("copy", "#A1A1AA", 11))
        btn_copy.setToolTip(self.i18n.t("btn_copy"))
        btn_copy.setStyleSheet("QPushButton { padding: 0; background: transparent; border: none; }")
        btn_copy.clicked.connect(lambda _c=False, t=entry.final_text: self._copy_text_safe(t))
        meta_row.addWidget(btn_copy)

        btn_del = QPushButton("")
        btn_del.setFixedSize(20, 20)
        btn_del.setIcon(make_flat_icon("trash", "#71717A", 11))
        btn_del.setToolTip(self.i18n.t("btn_delete"))
        btn_del.setStyleSheet("QPushButton { padding: 0; background: transparent; border: none; }")
        btn_del.clicked.connect(lambda _c=False, eid=entry.id: self._delete_history_entry(eid))
        meta_row.addWidget(btn_del)
        lay.addLayout(meta_row)

        txt_lbl = QLabel(entry.final_text)
        txt_lbl.setWordWrap(True)
        txt_lbl.setStyleSheet(
            "color: #FAFAFA; font-size: 8.8pt; font-weight: 500; border: none; line-height: 1.35;"
        )
        lay.addWidget(txt_lbl)

        if entry.raw_text.strip() and entry.raw_text.strip() != entry.final_text.strip():
            raw_lbl = QLabel(f"Raw: {entry.raw_text.strip()}")
            raw_lbl.setWordWrap(True)
            raw_lbl.setStyleSheet("color: #71717A; font-size: 7.5pt; border: none;")
            lay.addWidget(raw_lbl)

        return card

    def _copy_text_safe(self, text: str) -> None:
        try:
            pyperclip.copy(text)
        except Exception:
            pass

    def _toggle_pin_entry(self, entry_id: int) -> None:
        self.history.toggle_pin(entry_id)
        self.refresh_history()

    def _delete_history_entry(self, entry_id: int) -> None:
        self.history.delete(entry_id)
        self.refresh_history()

    def _clear_all_history(self) -> None:
        if not self._history_entries:
            return
        ans = QMessageBox.question(
            self,
            "LocalDictate",
            "Delete all saved dictation history permanently?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.refresh_history()

    def _export_history(self, fmt: str) -> None:
        ext = fmt.lower()
        dest, _ = QFileDialog.getSaveFileName(
            self,
            self.i18n.t("btn_export"),
            f"localdictate_history.{ext}",
            f"{ext.upper()} Files (*.{ext});;All Files (*)",
        )
        if not dest:
            return
        try:
            self.history.export_entries(dest, fmt=ext, entries=self._history_entries)
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))

    def _install_starter_pack(self, pack_id: str) -> None:
        current = _parse_rules_text(self.edit_snippets.toPlainText())
        merged = merge_starter_pack(current, pack_id)
        self.edit_snippets.setPlainText(_format_rules_text(merged))
        self._save_dictionary_panel()

    def _save_dictionary_panel(self) -> None:
        vocab = [w.strip() for w in self.edit_vocab.text().split(",") if w.strip()]
        rules = _parse_rules_text(self.edit_snippets.toPlainText())
        new_cfg = replace(
            self.controller.config,
            custom_vocabulary=vocab,
            snippets=rules,
            replacements={},
        )
        self.controller.apply_config(new_cfg, persist=True)
        self.config_applied.emit(new_cfg)

    # ═══════════════════════════════════════════════════════════════════════
    # SETTINGS, LLM TEST, UPDATER & BENCHMARK
    # ═══════════════════════════════════════════════════════════════════════
    def _apply_hotkey_preset(self, mode: str, hotkey: str) -> None:
        self._select_combo_data(self.combo_hk_mode, mode)
        if mode == "push_to_talk":
            self.edit_ptt_hk.setText(hotkey)
        else:
            self.edit_toggle_hk.setText(hotkey)

    def _clear_thread_ref(self, attr: str, thread: QThread) -> None:
        if getattr(self, attr, None) is thread:
            setattr(self, attr, None)

    def _shutdown_background_threads(self, wait_ms: int = 2000) -> None:
        """Cancel and cleanly wait on any active QThreads before window teardown."""
        for attr in ("_llm_test_thread", "_update_thread", "_bench_thread"):
            thread = getattr(self, attr, None)
            if thread is None:
                continue
            setattr(self, attr, None)
            try:
                thread.requestInterruption()
                cancel_fn = getattr(thread, "cancel", None)
                if callable(cancel_fn):
                    cancel_fn()
                if thread.isRunning():
                    thread.quit()
                    thread.wait(wait_ms)
            except RuntimeError:
                pass

    def _test_llm_async(self) -> None:
        if self._llm_test_thread is not None and self._llm_test_thread.isRunning():
            return
        backend = str(self.combo_llm_backend.currentData() or "ollama")
        url = self.edit_llm_url.text().strip() or "http://localhost:11434"
        api_key = self.edit_llm_apikey.text().strip()
        offline_lock = self.sw_offline_lock.isChecked()

        self.btn_test_llm.setEnabled(False)
        self.lbl_llm_status.setStyleSheet("color: #A78BFA; font-size: 7.6pt;")
        self.lbl_llm_status.setText("Testing connection...")

        thread = _LLMTestThread(backend, url, api_key, offline_lock, parent=self)
        thread.finished_probe.connect(self._on_llm_probe_finished)
        thread.finished.connect(lambda t=thread: self._clear_thread_ref("_llm_test_thread", t))
        thread.finished.connect(thread.deleteLater)
        self._llm_test_thread = thread
        thread.start()

    def _on_llm_probe_finished(self, models: list, error: str) -> None:
        self.btn_test_llm.setEnabled(True)
        if error:
            self.lbl_llm_status.setStyleSheet("color: #FB7185; font-size: 7.6pt;")
            self.lbl_llm_status.setText(f"Failed: {error}")
            return
        current = self.combo_llm_model.currentText().strip()
        self.combo_llm_model.clear()
        for m in models:
            self.combo_llm_model.addItem(m)
        if current:
            self.combo_llm_model.setCurrentText(current)
        self.lbl_llm_status.setStyleSheet("color: #10B981; font-size: 7.6pt;")
        self.lbl_llm_status.setText(f"Connected — {len(models)} model(s) ready.")

    def check_for_updates_async(self, silent: bool = False) -> None:
        if self.controller.config.offline_only and not silent:
            self.lbl_sys_feedback.setStyleSheet("color: #F59E0B; font-size: 7.8pt;")
            self.lbl_sys_feedback.setText(self.i18n.t("updates_offline_blocked"))
            return
        if self.controller.config.offline_only and silent:
            return
        if UpdateCheckerThread is None:
            return
        if self._update_thread is not None and self._update_thread.isRunning():
            return
        if not silent:
            self.lbl_sys_feedback.setStyleSheet("color: #A78BFA; font-size: 7.8pt;")
            self.lbl_sys_feedback.setText(self.i18n.t("updates_checking"))

        thread = UpdateCheckerThread(current_version=__version__, parent=self)
        thread.update_checked.connect(lambda info: self._on_update_checked(info, silent=silent))
        thread.finished.connect(lambda t=thread: self._clear_thread_ref("_update_thread", t))
        thread.finished.connect(thread.deleteLater)
        self._update_thread = thread
        thread.start()

    def _on_update_checked(self, info: UpdateInfo, silent: bool = False) -> None:
        self._latest_release_url = info.release_url
        if info.error:
            if not silent:
                self.lbl_sys_feedback.setStyleSheet("color: #A1A1AA; font-size: 7.8pt;")
                self.lbl_sys_feedback.setText(self.i18n.t("updates_error"))
            return
        if info.is_update_available:
            self.lbl_sys_feedback.setStyleSheet("color: #10B981; font-size: 7.8pt; font-weight: 600;")
            self.lbl_sys_feedback.setText(
                self.i18n.t("updates_available", latest=info.latest_version)
            )
            if not silent:
                ans = QMessageBox.question(
                    self,
                    "LocalDictate Update",
                    f"LocalDictate v{info.latest_version} is available. Open GitHub Release page?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if (
                    ans == QMessageBox.StandardButton.Yes
                    and info.release_url
                    and is_trusted_update_url(info.release_url)
                ):
                    webbrowser.open(info.release_url)
        elif not silent:
            self.lbl_sys_feedback.setStyleSheet("color: #10B981; font-size: 7.8pt;")
            self.lbl_sys_feedback.setText(self.i18n.t("updates_up_to_date", version=__version__))

    def _run_quick_benchmark(self) -> None:
        if self._bench_thread is not None and self._bench_thread.isRunning():
            return
        self.btn_run_bench.setEnabled(False)
        self.lbl_sys_feedback.setStyleSheet("color: #A78BFA; font-size: 7.8pt;")
        self.lbl_sys_feedback.setText(self.i18n.t("bench_running"))
        thread = _QuickBenchmarkThread(history=self.history, parent=self)
        thread.benchmark_done.connect(self._on_benchmark_done)
        thread.finished.connect(lambda t=thread: self._clear_thread_ref("_bench_thread", t))
        thread.finished.connect(thread.deleteLater)
        self._bench_thread = thread
        thread.start()

    def _on_benchmark_done(self, metrics: dict) -> None:
        self.btn_run_bench.setEnabled(True)
        self.lbl_sys_feedback.setStyleSheet("color: #10B981; font-size: 7.8pt; font-weight: 600;")
        self.lbl_sys_feedback.setText(
            self.i18n.t(
                "bench_done",
                vad=metrics["vad_ms"],
                snip=metrics["snippet_ms"],
                search=metrics["search_ms"],
            )
        )

    def _save_settings_from_ui(self) -> None:
        toggle_hk = self.edit_toggle_hk.text().strip() or self.controller.config.toggle_hotkey
        ptt_hk = self.edit_ptt_hk.text().strip() or self.controller.config.ptt_hotkey
        ui_lang = str(self.combo_ui_lang.currentData() or "en")
        model_sz = str(self.combo_settings_model.currentData() or self.controller.config.model_size)

        new_cfg = replace(
            self.controller.config,
            ui_language=ui_lang,
            hotkey_mode=str(self.combo_hk_mode.currentData() or "toggle"),
            toggle_hotkey=toggle_hk,
            ptt_hotkey=ptt_hk,
            model_size=model_sz,
            beam_size=self.spin_beam.value(),
            vad_filter=self.sw_vad.isChecked(),
            performance_profile=str(self.combo_perf_profile.currentData() or PROFILE_AUTO),
            input_device=self.combo_mic.currentData(),
            sound_effects=self.sw_sound_cues.isChecked(),
            silence_auto_stop_sec=float(self.spin_silence_stop.value()),
            max_recording_sec=int(self.spin_max_rec.value()),
            overlay_position=str(self.combo_overlay_pos.currentData() or "bottom_center"),
            restore_clipboard=self.sw_restore_clip.isChecked(),
            ollama_enabled=self.sw_llm_enabled.isChecked(),
            llm_backend=str(self.combo_llm_backend.currentData() or "ollama"),
            ollama_url=self.edit_llm_url.text().strip() or "http://localhost:11434",
            ollama_model=self.combo_llm_model.currentText().strip() or "qwen2.5:3b",
            llm_api_key=self.edit_llm_apikey.text().strip(),
            launch_at_startup=self.sw_autostart.isChecked(),
            minimize_to_tray=self.sw_min_tray.isChecked(),
            check_updates_on_startup=self.sw_auto_update.isChecked(),
        )
        self.controller.apply_config(new_cfg, persist=True)
        self.retranslate_ui(ui_lang)
        self._sync_ui_from_config()
        self.config_applied.emit(new_cfg)
        self.lbl_sys_feedback.setStyleSheet("color: #10B981; font-size: 7.8pt; font-weight: 600;")
        self.lbl_sys_feedback.setText("Settings saved.")

    def retranslate_ui(self, lang: str) -> None:
        """Apply live bilingual EN / TR UI retranslation across all tabs without restarting."""
        self.i18n.set_language(lang)
        self.lbl_app_subtitle.setText(self.i18n.t("app_subtitle"))
        self.btn_nav_studio.set_nav_text(self.i18n.t("nav_studio"))
        self.btn_nav_history.set_nav_text(self.i18n.t("nav_history"))
        self.btn_nav_settings.set_nav_text(self.i18n.t("nav_settings"))
        self._set_dictate_cta_style(recording=self.controller.state == AppState.RECORDING)
        self.btn_test_mic.setText(
            f"  {self.i18n.t('btn_stop_test' if self._mic_testing else 'btn_test_mic')}"
        )
        self.btn_drop_audio.setText(f"  {self.i18n.t('btn_drop_audio')}")
        self.lbl_stage_title.setText(self.i18n.t("stage_title"))
        self.lbl_raw_hdr.setText(self.i18n.t("lbl_raw_transcript"))
        self.lbl_ref_hdr.setText(self.i18n.t("lbl_refined_output"))
        self.lbl_drop_hint.setText(self.i18n.t("stage_drop_hint"))
        self.btn_stage_copy.setText(f"  {self.i18n.t('btn_copy')}")
        self.btn_stage_repaste.setText(f"  {self.i18n.t('btn_repaste')}")
        self.btn_stage_clear.setText(self.i18n.t("btn_clear"))
        self.lbl_mode_hdr.setText(self.i18n.t("lbl_mode_pills"))
        self.lbl_toggles_hdr.setText(self.i18n.t("lbl_toggles"))
        for mode_id, key in MODE_PILLS:
            if mode_id in self._mode_buttons:
                self._mode_buttons[mode_id].setText(self.i18n.t(key))
        self.sw_auto_paste.setText(self.i18n.t("sw_auto_paste"))
        self.sw_app_aware.setText(self.i18n.t("sw_app_aware"))
        self.sw_voice_cmds.setText(self.i18n.t("sw_voice_cmds"))
        self.sw_offline_lock.setText(self.i18n.t("sw_offline_lock"))
        self.kpi_dictations.set_title(self.i18n.t("kpi_dictations"))
        self.kpi_words.set_title(self.i18n.t("kpi_words"))
        self.kpi_saved.set_title(self.i18n.t("kpi_saved"))
        self.kpi_latency.set_title(self.i18n.t("kpi_latency"))
        self.edit_history_search.setPlaceholderText(self.i18n.t("search_placeholder"))
        self.lbl_dict_title.setText(self.i18n.t("dict_panel_title"))
        self.lbl_vocab.setText(self.i18n.t("dict_vocab_label"))
        self.lbl_snippets.setText(self.i18n.t("dict_snippets_label"))
        self.lbl_snippets_hint.setText(self.i18n.t("dict_snippets_hint"))
        self.btn_save_dict.setText(self.i18n.t("btn_save_settings"))
        self.btn_save_settings.setText(self.i18n.t("btn_save_settings"))
        self.btn_check_updates.setText(f"  {self.i18n.t('btn_check_updates')}")
        self.btn_run_bench.setText(f"  {self.i18n.t('btn_benchmark')}")
        self.lbl_hw_summary.setText(
            format_hardware_summary(self.controller.hw_profile, self.controller.tuning, lang=lang)
        )

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def request_force_quit(self) -> None:
        self._force_quit = True
        self._stop_mic_test()
        self._shutdown_background_threads()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_mic_test()
        if (
            not self._force_quit
            and self.controller.config.minimize_to_tray
            and QSystemTrayIcon.isSystemTrayAvailable()
        ):
            event.ignore()
            self.hide()
            return
        self._shutdown_background_threads()
        event.accept()
        app = QApplication.instance()
        if app is not None and not self._force_quit:
            app.quit()
