"""Searchable dictation history and productivity statistics window."""

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

from ..history import HistoryEntry, HistoryStore


HISTORY_STYLESHEET = """
QDialog {
    background-color: #11141c;
    color: #e2e8f0;
    font-family: "Segoe UI";
    font-size: 13px;
}
QFrame#StatCard {
    background-color: #191e2b;
    border: 1px solid #283144;
    border-radius: 10px;
    padding: 8px;
}
QLineEdit {
    background-color: #191e2b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 12px;
}
QLineEdit:focus {
    border-color: #6366f1;
}
QListWidget {
    background-color: #161a24;
    border: 1px solid #283144;
    border-radius: 10px;
    padding: 6px;
    outline: none;
}
QListWidget::item {
    background-color: #1d2332;
    border: 1px solid #293246;
    border-radius: 8px;
    padding: 10px;
    margin-bottom: 6px;
    color: #f1f5f9;
}
QListWidget::item:selected {
    background-color: #283149;
    border-color: #6366f1;
}
QPushButton {
    background-color: #242b3d;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 7px;
    padding: 7px 13px;
}
QPushButton:hover {
    background-color: #334155;
}
QPushButton#DangerBtn {
    background-color: #3b1d24;
    border-color: #7f1d1d;
    color: #fecaca;
}
QPushButton#DangerBtn:hover {
    background-color: #5c202d;
}
"""


class HistoryDialog(QDialog):
    """Displays local SQLite dictation history and time-saved statistics."""

    def __init__(self, store: HistoryStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._entries: list[HistoryEntry] = []

        self.setWindowTitle("LocalDictate — Dikte Geçmişi & İstatistikler")
        self.setMinimumSize(680, 520)
        self.setStyleSheet(HISTORY_STYLESHEET)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self._stat_dictations = self._make_stat_card("Toplam Dikte")
        self._stat_words = self._make_stat_card("Toplam Kelime")
        self._stat_latency = self._make_stat_card("Ort. Deşifre")
        self._stat_saved = self._make_stat_card("Tahmini Kazanç")
        for card, _ in (
            self._stat_dictations,
            self._stat_words,
            self._stat_latency,
            self._stat_saved,
        ):
            stats_row.addWidget(card)
        root.addLayout(stats_row)

        # Search input
        self._search = QLineEdit()
        self._search.setPlaceholderText("Geçmişte ara...")
        self._search.textChanged.connect(self.refresh)
        root.addWidget(self._search)

        # History list
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._copy_selected())
        root.addWidget(self._list, stretch=1)

        # Bottom actions
        actions = QHBoxLayout()
        self._status_lbl = QLabel("Çift tıklayarak metni panoya kopyalayabilirsiniz.")
        self._status_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        actions.addWidget(self._status_lbl, stretch=1)

        copy_btn = QPushButton("Kopyala")
        copy_btn.clicked.connect(self._copy_selected)
        actions.addWidget(copy_btn)

        delete_btn = QPushButton("Sil")
        delete_btn.clicked.connect(self._delete_selected)
        actions.addWidget(delete_btn)

        clear_btn = QPushButton("Tümünü Temizle")
        clear_btn.setObjectName("DangerBtn")
        clear_btn.clicked.connect(self._clear_all)
        actions.addWidget(clear_btn)

        close_btn = QPushButton("Kapat")
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
        val_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")

        lay.addWidget(val_lbl)
        lay.addWidget(title_lbl)
        return card, val_lbl

    def refresh(self) -> None:
        stats = self._store.get_stats()
        self._stat_dictations[1].setText(str(stats.total_dictations))
        self._stat_words[1].setText(f"{stats.total_words:,}".replace(",", "."))
        self._stat_latency[1].setText(f"{stats.avg_inference_sec:.2f}s")
        self._stat_saved[1].setText(f"~{stats.estimated_minutes_saved:.1f} dk")

        query = self._search.text()
        self._entries = self._store.list_recent(limit=150, query=query)
        self._list.clear()

        for entry in self._entries:
            ai_badge = " · AI" if entry.used_llm else ""
            meta = (
                f"{entry.created_at}  |  {entry.language.upper() or 'AUTO'}  |  "
                f"{entry.model_size}  |  {entry.inference_sec:.1f}s{ai_badge}"
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
            self._status_lbl.setText("Seçili metin panoya kopyalandı.")
        except Exception:
            self._status_lbl.setText("Panoya kopyalanamadı.")

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
            "Geçmişi Temizle",
            "Tüm dikte geçmişi kalıcı olarak silinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._store.clear()
            self.refresh()
