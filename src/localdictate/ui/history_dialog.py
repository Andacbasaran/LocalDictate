"""Standalone searchable dictation history dialog (Studio 2.0 palette, backwards-compatible)."""

from __future__ import annotations

import pyperclip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..hardware import get_ui_font_family
from ..history import HistoryEntry, HistoryStore


def _build_stylesheet() -> str:
    font = get_ui_font_family()
    return f"""
QDialog {{
    background-color: #0A0A0C;
    color: #FAFAFA;
    font-family: '{font}', 'Segoe UI', sans-serif;
    font-size: 13px;
}}
QFrame#StatCard {{
    background-color: #141417;
    border: 1px solid #24242A;
    border-radius: 10px;
    padding: 8px;
}}
QLineEdit {{
    background-color: #141417;
    color: #FAFAFA;
    border: 1px solid #26262E;
    border-radius: 8px;
    padding: 8px 12px;
}}
QLineEdit:focus {{
    border-color: #8B5CF6;
}}
QListWidget {{
    background-color: #111114;
    border: 1px solid #24242A;
    border-radius: 10px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    background-color: #141418;
    border: 1px solid #24242A;
    border-radius: 8px;
    padding: 10px;
    margin-bottom: 6px;
    color: #FAFAFA;
}}
QListWidget::item:selected {{
    background-color: #1E1930;
    border-color: #8B5CF6;
}}
QPushButton {{
    background-color: #1B1B21;
    color: #FAFAFA;
    border: 1px solid #2B2B34;
    border-radius: 7px;
    padding: 7px 13px;
}}
QPushButton:hover {{
    background-color: #23232B;
}}
QPushButton#DangerBtn {{
    background-color: #2B1018;
    border-color: #591C2E;
    color: #FB7185;
}}
"""


class HistoryDialog(QDialog):
    """Displays local SQLite dictation history and time-saved statistics."""

    def __init__(self, store: HistoryStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._entries: list[HistoryEntry] = []

        self.setWindowTitle("LocalDictate — History & Statistics")
        self.setMinimumSize(680, 520)
        self.setStyleSheet(_build_stylesheet())

        root = QVBoxLayout(self)
        root.setSpacing(12)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self._stat_dictations = self._make_stat_card("Total Dictations")
        self._stat_words = self._make_stat_card("Words Dictated")
        self._stat_latency = self._make_stat_card("Avg Latency")
        self._stat_saved = self._make_stat_card("Time Saved")
        for card, _ in (
            self._stat_dictations,
            self._stat_words,
            self._stat_latency,
            self._stat_saved,
        ):
            stats_row.addWidget(card)
        root.addLayout(stats_row)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search dictation history...")
        self._search.textChanged.connect(self.refresh)
        root.addWidget(self._search)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._copy_selected())
        root.addWidget(self._list, stretch=1)

        actions = QHBoxLayout()
        self._status_lbl = QLabel("Double-click an entry to copy it to the clipboard.")
        self._status_lbl.setStyleSheet("color: #71717A; font-size: 12px;")
        actions.addWidget(self._status_lbl, stretch=1)

        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy_selected)
        actions.addWidget(copy_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._delete_selected)
        actions.addWidget(delete_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.setObjectName("DangerBtn")
        clear_btn.clicked.connect(self._clear_all)
        actions.addWidget(clear_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)

        root.addLayout(actions)
        self.refresh()

    @staticmethod
    def _make_stat_card(title: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName("StatCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        val_lbl = QLabel("0")
        val_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #FAFAFA;")
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 11px; color: #71717A;")

        lay.addWidget(val_lbl)
        lay.addWidget(title_lbl)
        return card, val_lbl

    def refresh(self) -> None:
        stats = self._store.get_stats()
        self._stat_dictations[1].setText(str(stats.total_dictations))
        self._stat_words[1].setText(f"{stats.total_words:,}")
        self._stat_latency[1].setText(f"{stats.avg_inference_sec:.2f}s")
        self._stat_saved[1].setText(f"~{stats.estimated_minutes_saved:.1f} min")

        query = self._search.text()
        self._entries = self._store.list_recent(limit=150, query=query)
        self._list.clear()

        for entry in self._entries:
            ai_badge = " · LLM" if entry.used_llm else ""
            meta = (
                f"{entry.created_at}  |  {entry.language.upper() or 'AUTO'}  |  "
                f"{entry.mode}  |  {entry.inference_sec:.2f}s{ai_badge}"
            )
            item = QListWidgetItem(f"{entry.final_text}\n{meta}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self._list.addItem(item)

    def _selected_entry(self) -> HistoryEntry | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _copy_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        try:
            pyperclip.copy(entry.final_text)
            self._status_lbl.setText("Copied selected text to clipboard.")
        except Exception:
            self._status_lbl.setText("Failed to copy to clipboard.")

    def _delete_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        self._store.delete(entry.id)
        self.refresh()

    def _clear_all(self) -> None:
        if not self._entries:
            return
        ans = QMessageBox.question(
            self,
            "Clear History",
            "Permanently delete all saved dictation history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._store.clear()
            self.refresh()
