"""Application entry point for LocalDictate v1.0.0 with single-instance lock and crash logging."""

from __future__ import annotations

import getpass
import hashlib
import logging
import os
import sys
import threading
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

CRASH_LOG_MAX_BYTES = 512 * 1024


def _build_instance_server_name() -> str:
    """Scope the single-instance IPC socket name to the current OS user."""
    if hasattr(os, "getuid"):
        user_tag = str(os.getuid())
    else:
        try:
            user = getpass.getuser()
        except Exception:
            user = os.environ.get("USERNAME") or os.environ.get("USER") or "default"
        user_tag = hashlib.sha256(user.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{__bundle_id__}.ipc.{user_tag}"


INSTANCE_SERVER_NAME = _build_instance_server_name()


def _configure_frozen_ssl_certs() -> None:
    """Ensure frozen PyInstaller bundles locate certifi's CA bundle for HTTPS/TLS."""
    if getattr(sys, "frozen", False) and not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi

            ca_bundle = certifi.where()
            if ca_bundle and os.path.isfile(ca_bundle):
                os.environ["SSL_CERT_FILE"] = ca_bundle
                os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)
        except Exception:
            pass


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _write_crash_log(header: str, tb_text: str, max_bytes: int = CRASH_LOG_MAX_BYTES) -> None:
    """Append an unhandled exception record to crash.log with size-bounded rotation."""
    try:
        log_path = get_crash_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if log_path.exists() and log_path.stat().st_size >= max_bytes:
                rotated = log_path.with_name(f"{log_path.name}.1")
                os.replace(log_path, rotated)
        except OSError:
            pass
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n[{stamp}] LocalDictate v{__version__} {header}:\n{tb_text}\n")
    except Exception:
        pass


def _install_crash_logger() -> None:
    """Write unhandled main-thread and worker-thread exceptions to OS-native crash.log."""
    orig_hook = sys.excepthook
    orig_thread_hook = getattr(threading, "excepthook", None)

    def _handle_exception(exc_type, exc_value, exc_tb) -> None:
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash_log("unhandled exception", tb_text)
        orig_hook(exc_type, exc_value, exc_tb)

    def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is not SystemExit:
            thread_name = getattr(args.thread, "name", "unknown")
            tb_text = "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            )
            _write_crash_log(f"unhandled thread exception ({thread_name})", tb_text)
        if orig_thread_hook is not None:
            orig_thread_hook(args)

    sys.excepthook = _handle_exception
    threading.excepthook = _handle_thread_exception


def _notify_running_instance() -> bool:
    """If another LocalDictate instance is already active, signal it to raise its Studio window."""
    sock = QLocalSocket()
    try:
        sock.connectToServer(INSTANCE_SERVER_NAME)
        if sock.waitForConnected(250):
            sock.write(b"RAISE")
            sock.flush()
            sock.waitForBytesWritten(250)
            sock.disconnectFromServer()
            return True
        return False
    finally:
        sock.deleteLater()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    _configure_frozen_ssl_certs()
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
        ipc_server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
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

    shutting_down = False

    def quit_app() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        logger.info("Shutting down LocalDictate...")
        if ipc_server is not None:
            try:
                ipc_server.close()
            except Exception:
                pass
        controller.shutdown()
        overlay.hide()
        tray.hide()
        studio.request_force_quit()
        app.quit()

    app.aboutToQuit.connect(quit_app)

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
                conn.deleteLater()
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
