"""Application entry point for LocalDictate v1.0.0 with single-instance lock and crash logging."""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from . import __bundle_id__, __version__
from .config import get_crash_log_path, load_config
from .controller import DictationController
from .hardware import apply_thread_env_defaults, compute_runtime_tuning, detect_hardware_profile
from .history import HistoryStore
from .ui.overlay import FloatingOverlay
from .ui.studio_window import StudioWindow
from .ui.tray import TrayManager

INSTANCE_SERVER_NAME = f"{__bundle_id__}.ipc"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _install_crash_logger() -> None:
    """Write unhandled exceptions to OS-native crash.log without crashing the logger itself."""
    orig_hook = sys.excepthook

    def _handle_exception(exc_type, exc_value, exc_tb) -> None:
        try:
            log_path = get_crash_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n[{stamp}] LocalDictate v{__version__} unhandled exception:\n{tb_text}\n")
        except Exception:
            pass
        orig_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _handle_exception


def _notify_running_instance() -> bool:
    """If another LocalDictate instance is already active, signal it to raise its Studio window."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_SERVER_NAME)
    if sock.waitForConnected(250):
        sock.write(b"RAISE")
        sock.flush()
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    _setup_logging()
    _install_crash_logger()
    logger = logging.getLogger(__name__)

    start_minimized_arg = "--minimized" in args
    smoke_exit = "--smoke-test" in args

    app = QApplication(args)
    app.setApplicationName("LocalDictate")
    app.setApplicationVersion(__version__)

    tray_available = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not tray_available)

    # Single-instance guard (skip in smoke-test mode)
    ipc_server: QLocalServer | None = None
    if not smoke_exit:
        if _notify_running_instance():
            logger.info("LocalDictate is already running; brought existing window to front.")
            return 0
        QLocalServer.removeServer(INSTANCE_SERVER_NAME)
        ipc_server = QLocalServer()
        if not ipc_server.listen(INSTANCE_SERVER_NAME):
            logger.debug("Could not bind single-instance socket: %s", ipc_server.errorString())

    config = load_config()
    hw_profile = detect_hardware_profile(query_ct2=True)
    tuning = compute_runtime_tuning(
        hw_profile,
        requested_profile=config.performance_profile,
        preferred_compute_type=config.compute_type,
    )
    apply_thread_env_defaults(tuning)

    history_store = HistoryStore()
    controller = DictationController(
        config=config,
        history=history_store,
        hw_profile=hw_profile,
    )
    studio = StudioWindow(controller=controller, history=history_store)
    overlay = FloatingOverlay(
        position=config.overlay_position,
        mode=config.effective_style,
        language=config.language,
    )
    tray = TrayManager(active_hotkey=config.active_hotkey, i18n=studio.i18n)

    # Wire controller signals to HUD 2.0 & TrayManager
    controller.state_changed.connect(overlay.on_state_changed)
    controller.state_changed.connect(tray.on_state_changed)
    controller.audio_level.connect(overlay.on_audio_level)
    controller.active_context_changed.connect(
        lambda _app, mode: overlay.set_context_badge(mode, controller.config.language)
    )
    controller.transcription_done.connect(lambda _txt, _sec: tray.enable_copy_last(True))

    def on_config_applied(new_cfg) -> None:
        overlay.set_position(new_cfg.overlay_position)
        overlay.set_context_badge(new_cfg.effective_style, new_cfg.language)
        tray.update_hotkey_label(new_cfg.active_hotkey)
        tray.retranslate(studio.i18n)

    studio.config_applied.connect(on_config_applied)

    def open_studio(tab_idx: int = 0) -> None:
        studio.switch_tab(tab_idx)
        studio.bring_to_front()

    def quit_app() -> None:
        logger.info("Shutting down LocalDictate...")
        if ipc_server is not None:
            ipc_server.close()
        controller.shutdown()
        overlay.hide()
        tray.hide()
        studio.request_force_quit()
        app.quit()

    tray.open_studio_requested.connect(lambda: open_studio(0))
    tray.history_requested.connect(lambda: open_studio(1))
    tray.settings_requested.connect(lambda: open_studio(2))
    tray.copy_last_requested.connect(controller.copy_last_text)
    tray.toggle_requested.connect(controller.toggle_recording)
    tray.quit_requested.connect(quit_app)

    if ipc_server is not None:
        def _on_ipc_connection() -> None:
            conn = ipc_server.nextPendingConnection()
            if conn is not None:
                conn.readAll()
                conn.disconnectFromServer()
            open_studio(0)

        ipc_server.newConnection.connect(_on_ipc_connection)

    if tray_available:
        tray.show()
    else:
        logger.info("System tray unavailable on this desktop; running in full Studio window mode.")

    # Open directly to Studio 2.0 unless explicitly launched minimized with a working tray
    if not (tray_available and (start_minimized_arg or config.start_minimized)):
        studio.show()

    if smoke_exit:
        QTimer.singleShot(250, quit_app)
        return app.exec()

    controller.start()
    if config.check_updates_on_startup and not config.offline_only:
        QTimer.singleShot(2500, lambda: studio.check_for_updates_async(silent=True))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
