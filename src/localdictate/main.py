"""Application entry point for LocalDictate."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from .config import load_config
from .controller import DictationController
from .history import HistoryStore
from .ui.history_dialog import HistoryDialog
from .ui.overlay import FloatingOverlay
from .ui.settings_dialog import SettingsDialog
from .ui.tray import TrayManager


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    _setup_logging()
    logger = logging.getLogger(__name__)

    app = QApplication(sys.argv)
    app.setApplicationName("LocalDictate")
    app.setQuitOnLastWindowClosed(False)

    config = load_config()
    history_store = HistoryStore()
    controller = DictationController(config=config, history=history_store)
    overlay = FloatingOverlay(position=config.overlay_position)
    tray = TrayManager(active_hotkey=config.active_hotkey)

    # Wire controller signals to UI
    controller.state_changed.connect(overlay.on_state_changed)
    controller.state_changed.connect(tray.on_state_changed)
    controller.audio_level.connect(overlay.on_audio_level)
    controller.transcription_done.connect(lambda _txt, _sec: tray.enable_copy_last(True))

    settings_window: list[SettingsDialog] = []
    history_window: list[HistoryDialog] = []

    def open_settings() -> None:
        if settings_window:
            dlg = settings_window[0]
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = SettingsDialog(controller.config)
        settings_window.append(dlg)
        try:
            if dlg.exec():
                new_cfg = dlg.build_config()
                controller.apply_config(new_cfg, persist=True)
                overlay.set_position(new_cfg.overlay_position)
                tray.update_hotkey_label(new_cfg.active_hotkey)
                logger.info("Configuration updated")
        finally:
            settings_window.clear()

    def open_history() -> None:
        if history_window:
            dlg = history_window[0]
            dlg.refresh()
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = HistoryDialog(history_store)
        history_window.append(dlg)
        try:
            dlg.exec()
        finally:
            history_window.clear()

    def quit_app() -> None:
        logger.info("Shutting down LocalDictate...")
        controller.shutdown()
        tray.hide()
        app.quit()

    tray.settings_requested.connect(open_settings)
    tray.history_requested.connect(open_history)
    tray.copy_last_requested.connect(controller.copy_last_text)
    tray.toggle_requested.connect(controller.toggle_recording)
    tray.quit_requested.connect(quit_app)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()
        tray.showMessage(
            "LocalDictate",
            f"Arka planda hazır. Kısayol: {config.active_hotkey}",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )
    else:
        logger.warning("System tray is not available on this desktop environment.")

    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
