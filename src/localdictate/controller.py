"""Core state machine orchestrating Hotkey -> Audio -> Whisper -> TextInjector -> UI."""

from __future__ import annotations

import logging
import threading
from enum import Enum

from PyQt6.QtCore import QObject, pyqtSignal

from .audio import AudioRecorder
from .config import AppConfig, save_config
from .hotkeys import HotkeyManager
from .injector import TextInjector
from .transcriber import WhisperTranscriber

logger = logging.getLogger(__name__)


class AppState(str, Enum):
    LOADING_MODEL = "loading_model"
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    ERROR = "error"


class DictationController(QObject):
    """Coordinates audio capture, local Whisper transcription, and text injection."""

    state_changed = pyqtSignal(str, str)  # (AppState.value, message)
    audio_level = pyqtSignal(float)  # 0.0 .. 1.0
    transcription_done = pyqtSignal(str, float)  # (text, inference_sec)
    model_ready = pyqtSignal(str)  # model_size
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        config: AppConfig,
        recorder: AudioRecorder | None = None,
        transcriber: WhisperTranscriber | None = None,
        injector: TextInjector | None = None,
        hotkey_manager: HotkeyManager | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self._state_lock = threading.Lock()
        self._state = AppState.IDLE
        self._model_loading = False

        self.recorder = recorder or AudioRecorder(
            device=config.input_device,
            on_level=self._on_audio_level,
        )
        self.transcriber = transcriber or WhisperTranscriber(
            model_size=config.model_size,
            compute_type=config.compute_type,
            cpu_threads=config.cpu_threads,
            vad_filter=config.vad_filter,
            beam_size=config.beam_size,
        )
        self.injector = injector or TextInjector(
            restore_clipboard=config.restore_clipboard,
            paste_delay_ms=config.paste_delay_ms,
        )
        self.hotkey_manager = hotkey_manager or HotkeyManager(
            mode=config.hotkey_mode,
            hotkey=config.active_hotkey,
            on_toggle=self.toggle_recording,
            on_ptt_start=self.start_recording,
            on_ptt_stop=self.stop_recording,
            on_cancel=self.cancel_recording,
        )

    @property
    def state(self) -> AppState:
        with self._state_lock:
            return self._state

    def start(self) -> None:
        """Start global hotkey listener and preload Whisper model in background."""
        self.hotkey_manager.start()
        self.preload_model()

    def shutdown(self) -> None:
        """Cleanly release hotkey hooks and audio streams."""
        self.hotkey_manager.stop()
        if self.recorder.is_recording:
            self.recorder.cancel()

    def preload_model(self) -> None:
        """Load the configured Whisper model asynchronously."""
        with self._state_lock:
            if self._model_loading:
                return
            self._model_loading = True
            self._state = AppState.LOADING_MODEL
        self.state_changed.emit(
            AppState.LOADING_MODEL.value,
            f"Model yükleniyor ({self.config.model_size})...",
        )
        threading.Thread(target=self._load_model_worker, daemon=True).start()

    def _load_model_worker(self) -> None:
        try:
            self.transcriber.load()
            with self._state_lock:
                self._model_loading = False
                if self._state == AppState.LOADING_MODEL:
                    self._state = AppState.IDLE
            self.model_ready.emit(self.config.model_size)
            self.state_changed.emit(AppState.IDLE.value, "Hazır")
        except Exception as exc:
            logger.exception("Failed to load Whisper model")
            with self._state_lock:
                self._model_loading = False
                self._state = AppState.ERROR
            msg = f"Model yüklenemedi: {exc}"
            self.error_occurred.emit(msg)
            self.state_changed.emit(AppState.ERROR.value, msg)

    def toggle_recording(self) -> None:
        """Toggle between IDLE and RECORDING states."""
        current = self.state
        if current == AppState.RECORDING:
            self.stop_recording()
        elif current in (AppState.IDLE, AppState.ERROR):
            self.start_recording()
        elif current == AppState.LOADING_MODEL:
            self.state_changed.emit(
                AppState.LOADING_MODEL.value,
                f"Model hâlâ yükleniyor ({self.config.model_size})...",
            )

    def start_recording(self) -> None:
        """Begin microphone capture if idle."""
        with self._state_lock:
            if self._state not in (AppState.IDLE, AppState.ERROR):
                return
            self._state = AppState.RECORDING

        try:
            self.recorder.start()
        except Exception as exc:
            logger.exception("Failed to start microphone recording")
            with self._state_lock:
                self._state = AppState.ERROR
            msg = f"Mikrofon açılamadı: {exc}"
            self.error_occurred.emit(msg)
            self.state_changed.emit(AppState.ERROR.value, msg)
            return

        self.state_changed.emit(AppState.RECORDING.value, "Dinleniyor...")

    def stop_recording(self) -> None:
        """Stop microphone capture and kick off background transcription."""
        with self._state_lock:
            if self._state != AppState.RECORDING:
                return
            self._state = AppState.TRANSCRIBING

        audio, duration = self.recorder.stop()
        if duration < 0.2 or audio.size == 0:
            with self._state_lock:
                self._state = AppState.IDLE
            self.state_changed.emit(AppState.IDLE.value, "Kayıt çok kısa")
            return

        self.state_changed.emit(AppState.TRANSCRIBING.value, "Çözümleniyor...")
        threading.Thread(
            target=self._transcribe_worker,
            args=(audio,),
            daemon=True,
        ).start()

    def cancel_recording(self) -> None:
        """Cancel an active recording without transcribing."""
        with self._state_lock:
            if self._state != AppState.RECORDING:
                return
            self._state = AppState.IDLE

        self.recorder.cancel()
        self.state_changed.emit(AppState.IDLE.value, "İptal edildi")

    def _transcribe_worker(self, audio) -> None:
        try:
            result = self.transcriber.transcribe(audio, language=self.config.language)
            if result.text:
                self.injector.inject(result.text)
                self.transcription_done.emit(result.text, result.inference_sec)
                with self._state_lock:
                    self._state = AppState.IDLE
                self.state_changed.emit(
                    AppState.IDLE.value,
                    f"Yapıştırıldı ({result.inference_sec:.1f}s)",
                )
            else:
                with self._state_lock:
                    self._state = AppState.IDLE
                self.state_changed.emit(AppState.IDLE.value, "Konuşma algılanmadı")
        except Exception as exc:
            logger.exception("Transcription failed")
            with self._state_lock:
                self._state = AppState.ERROR
            msg = f"Deşifre hatası: {exc}"
            self.error_occurred.emit(msg)
            self.state_changed.emit(AppState.ERROR.value, msg)

    def apply_config(self, new_config: AppConfig, persist: bool = True) -> None:
        """Apply updated user configuration live."""
        self.config = new_config
        if persist:
            save_config(new_config)

        self.recorder.device = new_config.input_device
        self.injector.restore_clipboard = new_config.restore_clipboard
        self.injector.paste_delay_ms = new_config.paste_delay_ms
        self.hotkey_manager.update(new_config.hotkey_mode, new_config.active_hotkey)

        needs_reload = self.transcriber.configure(
            model_size=new_config.model_size,
            compute_type=new_config.compute_type,
            cpu_threads=new_config.cpu_threads,
            vad_filter=new_config.vad_filter,
            beam_size=new_config.beam_size,
        )
        if needs_reload:
            self.preload_model()

    def _on_audio_level(self, level: float) -> None:
        self.audio_level.emit(level)
