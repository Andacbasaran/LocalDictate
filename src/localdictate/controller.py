"""Core state machine orchestrating Hotkey -> Audio -> Whisper -> PostProcess -> Injector -> History -> UI."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import pyperclip
from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal

from .audio import SAMPLE_RATE, AudioRecorder, load_audio_file, resample_audio
from .autostart import set_autostart
from .config import AppConfig, save_config
from .hardware import HardwareProfile, compute_runtime_tuning, detect_hardware_profile
from .history import HistoryStore
from .hotkeys import HotkeyManager
from .i18n import LanguageManager
from .injector import TextInjector
from .platform_utils import get_active_app_name, infer_mode_for_app
from .postprocess import TextPostProcessor
from .sounds import play_error_cue, play_start_cue, play_stop_cue
from .transcriber import WhisperTranscriber

logger = logging.getLogger(__name__)


class AppState(str, Enum):
    LOADING_MODEL = "loading_model"
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    REFINING = "refining"
    ERROR = "error"


@dataclass
class DictationOutcome:
    raw_text: str
    final_text: str
    language: str
    mode: str
    target_app: str
    audio_duration_sec: float
    stt_sec: float
    llm_sec: float
    paste_sec: float
    used_llm: bool
    pasted: bool
    wpm: int


class DictationController(QObject):
    """Coordinates audio capture, Whisper STT, LLM refinement, history, and safe text injection."""

    state_changed = pyqtSignal(str, str)  # (AppState.value, message)
    audio_level = pyqtSignal(float)  # 0.0 .. 1.0 (emitted safely from Qt main-thread QTimer)
    transcription_done = pyqtSignal(str, float)  # (final_text, inference_sec)
    dictation_completed = pyqtSignal(object)  # DictationOutcome
    model_ready = pyqtSignal(str)  # model_size
    error_occurred = pyqtSignal(str)
    active_context_changed = pyqtSignal(str, str)  # (target_app, resolved_mode)
    recording_starting = pyqtSignal()  # emitted before recorder.start() to stop mic test cleanly

    def __init__(
        self,
        config: AppConfig,
        recorder: AudioRecorder | None = None,
        transcriber: WhisperTranscriber | None = None,
        postprocessor: TextPostProcessor | None = None,
        injector: TextInjector | None = None,
        hotkey_manager: HotkeyManager | None = None,
        history: HistoryStore | None = None,
        active_app_detector: Optional[Callable[[], str]] = None,
        hw_profile: Optional[HardwareProfile] = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.i18n = LanguageManager(config.ui_language)
        self.hw_profile = hw_profile or detect_hardware_profile(query_ct2=False)
        self.tuning = compute_runtime_tuning(
            self.hw_profile,
            requested_profile=config.performance_profile,
            preferred_compute_type=config.compute_type,
        )

        self._state_lock = threading.Lock()
        self._recorder_lock = threading.Lock()
        self._state = AppState.IDLE
        self._session_gen: int = 0
        self._model_loading = False
        self._reload_pending = False
        self.last_text: str = ""
        self.last_raw_text: str = ""
        self.last_outcome: Optional[DictationOutcome] = None
        self._active_target_app: str = ""
        self._active_mode: str = config.effective_style
        self._active_app_detector = active_app_detector or get_active_app_name

        # Recorder never emits Qt signals from PortAudio's C callback thread!
        self.recorder = recorder or AudioRecorder(
            device=config.input_device,
            on_level=None,
            max_duration_sec=float(config.max_recording_sec),
            silence_auto_stop_sec=float(config.silence_auto_stop_sec),
            on_auto_stop=self._on_recorder_auto_stop,
        )
        self.transcriber = transcriber or WhisperTranscriber(
            model_size=config.model_size,
            compute_type=config.compute_type,
            cpu_threads=config.cpu_threads,
            vad_filter=config.vad_filter,
            beam_size=config.beam_size,
            performance_profile=config.performance_profile,
            hw_profile=self.hw_profile,
            offline_only=config.offline_only,
        )
        self.postprocessor = postprocessor or TextPostProcessor(config=config)
        self.injector = injector or TextInjector(
            restore_clipboard=config.restore_clipboard,
            paste_delay_ms=config.paste_delay_ms,
            clipboard_restore_delay_ms=config.clipboard_restore_delay_ms,
            direct_typing_fallback=config.direct_typing_fallback,
        )
        self.history = history
        self.hotkey_manager = hotkey_manager or HotkeyManager(
            mode=config.hotkey_mode,
            hotkey=config.active_hotkey,
            on_toggle=self.toggle_recording,
            on_ptt_start=self.start_recording,
            on_ptt_stop=self.stop_recording,
            on_cancel=self.cancel_recording,
        )

        # Poll audio levels safely on the Qt main thread (30 Hz) when a Qt event loop exists
        self._meter_timer: Optional[QTimer] = None
        if QCoreApplication.instance() is not None:
            self._meter_timer = QTimer(self)
            self._meter_timer.setInterval(33)
            self._meter_timer.timeout.connect(self._poll_audio_level)

    @property
    def state(self) -> AppState:
        with self._state_lock:
            return self._state

    @property
    def active_mode(self) -> str:
        return self._active_mode

    @property
    def active_target_app(self) -> str:
        return self._active_target_app

    def _poll_audio_level(self) -> None:
        if self.state == AppState.RECORDING:
            getter = getattr(self.recorder, "get_latest_level", None)
            if callable(getter):
                try:
                    self.audio_level.emit(float(getter()))
                except Exception:
                    pass
        elif self._meter_timer is not None and self._meter_timer.isActive():
            self._meter_timer.stop()

    def _start_meter_timer(self) -> None:
        if self._meter_timer is not None and QCoreApplication.instance() is not None:
            try:
                QTimer.singleShot(0, self._meter_timer.start)
            except Exception:
                pass

    def _stop_meter_timer(self) -> None:
        if self._meter_timer is not None and QCoreApplication.instance() is not None:
            try:
                QTimer.singleShot(0, self._meter_timer.stop)
            except Exception:
                pass

    def _on_recorder_auto_stop(self, reason: str) -> None:
        logger.info("Auto-stopping recording (reason=%s)", reason)
        self.stop_recording()

    def start(self) -> None:
        """Start global hotkey listener and preload Whisper model in background."""
        self.hotkey_manager.start()
        self.preload_model()

    def shutdown(self) -> None:
        """Cleanly release hotkey hooks, audio streams, and SQLite connection."""
        with self._state_lock:
            self._session_gen += 1
            self._reload_pending = False
            self._state = AppState.IDLE
        self._stop_meter_timer()
        self.hotkey_manager.stop()
        with self._recorder_lock:
            if self.recorder.is_recording:
                self.recorder.cancel()
        if self.history is not None:
            close_fn = getattr(self.history, "close", None)
            if callable(close_fn):
                close_fn()

    def copy_last_text(self) -> bool:
        """Copy the most recent dictated text to clipboard."""
        if not self.last_text:
            return False
        try:
            pyperclip.copy(self.last_text)
            self.state_changed.emit(AppState.IDLE.value, self.i18n.t("status_copied_last"))
            return True
        except Exception:
            return False

    def repaste_last_text(self) -> bool:
        """Re-inject the last dictated text into the currently focused application."""
        if not self.last_text:
            return False
        return bool(self.injector.inject(self.last_text))

    def set_dictation_mode(self, mode: str, persist: bool = True) -> None:
        """Switch active dictation mode (cleanup / formal / concise / code / bullet_notes / git_commit / translate_en)."""
        self.config.dictation_mode = mode
        self.config.ollama_style = mode
        self.config.translate_to_english = mode == "translate_en"
        self._active_mode = mode
        if persist:
            save_config(self.config)
        self.active_context_changed.emit(self._active_target_app, mode)

    def _maybe_trigger_pending_reload(self) -> None:
        """Run any deferred model reload once the controller has returned to IDLE."""
        with self._state_lock:
            should_reload = (
                self._reload_pending
                and not self._model_loading
                and self._state == AppState.IDLE
            )
        if should_reload:
            self.preload_model()

    def preload_model(self) -> None:
        """Load the configured Whisper model asynchronously, deferring if busy."""
        with self._state_lock:
            if self._model_loading:
                self._reload_pending = True
                return
            if self._state in (AppState.RECORDING, AppState.TRANSCRIBING, AppState.REFINING):
                self._reload_pending = True
                return
            self._reload_pending = False
            self._model_loading = True
            self._state = AppState.LOADING_MODEL
        self.state_changed.emit(
            AppState.LOADING_MODEL.value,
            self.i18n.t("status_loading_model", model=self.config.model_size),
        )
        threading.Thread(target=self._load_model_worker, daemon=True).start()

    def _load_model_worker(self) -> None:
        try:
            self.transcriber.load()
            reload_again = False
            with self._state_lock:
                self._model_loading = False
                if self._reload_pending:
                    self._reload_pending = False
                    reload_again = True
                    if self._state == AppState.LOADING_MODEL:
                        self._state = AppState.IDLE
                elif self._state == AppState.LOADING_MODEL:
                    self._state = AppState.IDLE
            if reload_again:
                self.preload_model()
                return
            self.model_ready.emit(self.config.model_size)
            self.state_changed.emit(AppState.IDLE.value, self.i18n.t("status_ready"))
        except Exception as exc:
            logger.exception("Failed to load Whisper model")
            with self._state_lock:
                self._model_loading = False
                self._reload_pending = False
                self._state = AppState.ERROR
            play_error_cue(self.config.sound_effects)
            msg = self.i18n.t("status_model_error", err=exc)
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
                self.i18n.t("status_loading_model", model=self.config.model_size),
            )

    def _resolve_active_context(self) -> tuple[str, str]:
        """Detect foreground app and choose mode if App-Aware Auto-Mode Routing is enabled."""
        target_app = ""
        try:
            target_app = (self._active_app_detector() or "").strip()
        except Exception:
            target_app = ""

        # Do not route against our own Studio window; preserve user's chosen mode there
        is_self_window = target_app.lower() in ("localdictate", "python", "python3", "pythonw")
        if (
            self.config.app_aware_routing
            and target_app
            and not is_self_window
            and self.config.effective_style != "translate_en"
        ):
            resolved_mode = infer_mode_for_app(
                target_app,
                custom_rules=self.config.app_mode_rules,
                default_mode=self.config.effective_style,
            )
        else:
            resolved_mode = self.config.effective_style

        self._active_target_app = target_app
        self._active_mode = resolved_mode
        self.active_context_changed.emit(target_app, resolved_mode)
        return target_app, resolved_mode

    def start_recording(self) -> None:
        """Begin microphone capture if idle, playing start chime cleanly before capture."""
        with self._state_lock:
            if self._state not in (AppState.IDLE, AppState.ERROR):
                return
            self._session_gen += 1
            my_gen = self._session_gen
            self._state = AppState.RECORDING

        self.recording_starting.emit()
        self._resolve_active_context()

        # Play crisp start chime BEFORE opening microphone stream to prevent acoustic bleed
        play_start_cue(self.config.sound_effects, wait=True)

        with self._recorder_lock:
            with self._state_lock:
                if self._session_gen != my_gen or self._state != AppState.RECORDING:
                    return

            try:
                self.recorder.start()
            except Exception as exc:
                logger.exception("Failed to start microphone recording")
                with self._state_lock:
                    if self._session_gen != my_gen:
                        return
                    self._state = AppState.ERROR
                play_error_cue(self.config.sound_effects)
                msg = self.i18n.t("status_mic_error", err=exc)
                self.error_occurred.emit(msg)
                self.state_changed.emit(AppState.ERROR.value, msg)
                return

            with self._state_lock:
                aborted = self._session_gen != my_gen or self._state != AppState.RECORDING

            if aborted:
                try:
                    self.recorder.cancel()
                except Exception:
                    pass
                return

        self._start_meter_timer()
        self.state_changed.emit(AppState.RECORDING.value, self.i18n.t("status_listening"))

    def stop_recording(self) -> None:
        """Stop microphone capture and kick off background transcription."""
        with self._state_lock:
            if self._state != AppState.RECORDING:
                return
            self._session_gen += 1
            stop_gen = self._session_gen
            self._state = AppState.TRANSCRIBING

        self._stop_meter_timer()
        with self._recorder_lock:
            if isinstance(self.recorder, AudioRecorder):
                audio, duration = self.recorder.stop(resample=False)
                capture_sr = self.recorder.capture_sample_rate
            else:
                audio, duration = self.recorder.stop()
                raw_sr = getattr(self.recorder, "capture_sample_rate", SAMPLE_RATE)
                capture_sr = raw_sr if isinstance(raw_sr, int) and raw_sr > 0 else SAMPLE_RATE

        play_stop_cue(self.config.sound_effects)

        if duration < 0.2 or audio.size == 0:
            with self._state_lock:
                if self._session_gen == stop_gen:
                    self._state = AppState.IDLE
            self.state_changed.emit(AppState.IDLE.value, self.i18n.t("status_too_short"))
            self._maybe_trigger_pending_reload()
            return

        self.state_changed.emit(AppState.TRANSCRIBING.value, self.i18n.t("status_transcribing"))
        threading.Thread(
            target=self._transcribe_worker,
            args=(audio, self._active_target_app, self._active_mode, True, capture_sr),
            daemon=True,
        ).start()

    def cancel_recording(self) -> None:
        """Cancel an active recording without transcribing."""
        with self._state_lock:
            if self._state != AppState.RECORDING:
                return
            self._session_gen += 1
            self._state = AppState.IDLE

        self._stop_meter_timer()
        with self._recorder_lock:
            self.recorder.cancel()
        play_stop_cue(self.config.sound_effects)
        self.state_changed.emit(AppState.IDLE.value, self.i18n.t("status_cancelled"))
        self._maybe_trigger_pending_reload()

    def transcribe_audio_file(self, file_path: Path | str) -> None:
        """Transcribe a dropped offline audio file (.wav/.mp3/.m4a/.flac/.ogg) asynchronously."""
        with self._state_lock:
            if self._state not in (AppState.IDLE, AppState.ERROR):
                return
            self._state = AppState.TRANSCRIBING

        p = Path(file_path)
        self.state_changed.emit(
            AppState.TRANSCRIBING.value,
            f"{self.i18n.t('status_transcribing')} ({p.name})",
        )

        def _file_worker() -> None:
            try:
                audio, _dur = load_audio_file(p)
                self._transcribe_worker(
                    audio,
                    target_app=f"File:{p.name}",
                    mode=self.config.effective_style,
                    allow_paste=False,
                )
            except Exception as exc:
                logger.exception("Failed to transcribe audio file")
                with self._state_lock:
                    self._state = AppState.ERROR
                play_error_cue(self.config.sound_effects)
                msg = self.i18n.t("status_transcribe_error", err=exc)
                self.error_occurred.emit(msg)
                self.state_changed.emit(AppState.ERROR.value, msg)

        threading.Thread(target=_file_worker, daemon=True).start()

    def _transcribe_worker(
        self,
        audio,
        target_app: str = "",
        mode: str = "cleanup",
        allow_paste: bool = True,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        cfg = replace(
            self.config,
            custom_vocabulary=list(self.config.custom_vocabulary),
            replacements=dict(self.config.replacements),
            snippets=dict(self.config.snippets),
            app_mode_rules=dict(self.config.app_mode_rules),
            custom_mode_prompts=dict(self.config.custom_mode_prompts),
        )
        try:
            if sample_rate != SAMPLE_RATE:
                audio = resample_audio(audio, sample_rate, SAMPLE_RATE)

            initial_prompt = cfg.build_initial_prompt()
            use_translate = mode == "translate_en" or cfg.translate_to_english
            task = "translate" if use_translate else "transcribe"

            transcribe_kwargs = {
                "language": cfg.language,
                "initial_prompt": initial_prompt,
            }
            if task == "translate":
                transcribe_kwargs["task"] = "translate"

            result = self.transcriber.transcribe(audio, **transcribe_kwargs)

            if not result.text:
                with self._state_lock:
                    self._state = AppState.IDLE
                self.state_changed.emit(AppState.IDLE.value, self.i18n.t("status_no_speech"))
                self._maybe_trigger_pending_reload()
                return

            if cfg.ollama_enabled:
                with self._state_lock:
                    self._state = AppState.REFINING
                self.state_changed.emit(AppState.REFINING.value, self.i18n.t("status_refining"))

            if isinstance(self.postprocessor, TextPostProcessor):
                processed = self.postprocessor.process(
                    result.text,
                    mode=mode,
                    detected_language=result.language,
                    config=cfg,
                )
            else:
                processed = self.postprocessor.process(
                    result.text,
                    mode=mode,
                    detected_language=result.language,
                )
            final_text = processed.final_text

            if not final_text.strip():
                with self._state_lock:
                    self._state = AppState.IDLE
                self.state_changed.emit(AppState.IDLE.value, self.i18n.t("status_no_speech"))
                self._maybe_trigger_pending_reload()
                return

            self.last_raw_text = result.text.strip()
            self.last_text = final_text.strip()

            t_paste = time.perf_counter()
            pasted = False
            if allow_paste and cfg.auto_paste:
                if target_app:
                    pasted = bool(self.injector.inject(final_text, target_app=target_app))
                else:
                    pasted = bool(self.injector.inject(final_text))
            else:
                self.injector.copy_only(final_text)
            paste_sec = time.perf_counter() - t_paste

            if cfg.save_history and self.history is not None:
                try:
                    self.history.add(
                        raw_text=result.text,
                        final_text=self.last_text,
                        language=result.language,
                        model_size=cfg.model_size,
                        audio_duration_sec=result.duration_sec,
                        inference_sec=result.inference_sec,
                        used_llm=processed.used_llm,
                        target_app=target_app,
                        mode=mode,
                    )
                except Exception:
                    logger.exception("Failed to save dictation to history")

            words = len(self.last_text.split())
            wpm = (
                int(round((words / result.duration_sec) * 60.0))
                if result.duration_sec > 0.05
                else 0
            )
            outcome = DictationOutcome(
                raw_text=self.last_raw_text,
                final_text=self.last_text,
                language=result.language or cfg.language,
                mode=mode,
                target_app=target_app,
                audio_duration_sec=result.duration_sec,
                stt_sec=result.inference_sec,
                llm_sec=processed.llm_sec,
                paste_sec=paste_sec,
                used_llm=processed.used_llm,
                pasted=pasted,
                wpm=wpm,
            )
            self.last_outcome = outcome

            self.transcription_done.emit(final_text, result.inference_sec)
            self.dictation_completed.emit(outcome)

            with self._state_lock:
                self._state = AppState.IDLE

            suffix = " · LLM" if processed.used_llm else ""
            status_key = "status_pasted" if pasted else "status_copied"
            self.state_changed.emit(
                AppState.IDLE.value,
                self.i18n.t(status_key, sec=result.inference_sec, suffix=suffix),
            )
            self._maybe_trigger_pending_reload()
        except Exception as exc:
            logger.exception("Transcription failed")
            with self._state_lock:
                self._state = AppState.ERROR
            play_error_cue(cfg.sound_effects)
            msg = self.i18n.t("status_transcribe_error", err=exc)
            self.error_occurred.emit(msg)
            self.state_changed.emit(AppState.ERROR.value, msg)

    def apply_config(self, new_config: AppConfig, persist: bool = True) -> None:
        """Apply updated user configuration live."""
        prev_startup = self.config.launch_at_startup
        self.config = new_config
        self.i18n.set_language(new_config.ui_language)
        self.postprocessor.config = new_config
        self._active_mode = new_config.effective_style

        self.tuning = compute_runtime_tuning(
            self.hw_profile,
            requested_profile=new_config.performance_profile,
            preferred_compute_type=new_config.compute_type,
        )

        if persist:
            save_config(new_config)
            if new_config.launch_at_startup != prev_startup:
                set_autostart(new_config.launch_at_startup)

        self.recorder.device = new_config.input_device
        self.recorder.max_duration_sec = max(5.0, float(new_config.max_recording_sec))
        self.recorder.silence_auto_stop_sec = max(0.0, float(new_config.silence_auto_stop_sec))

        self.injector.restore_clipboard = new_config.restore_clipboard
        self.injector.paste_delay_ms = new_config.paste_delay_ms
        self.injector.clipboard_restore_delay_ms = new_config.clipboard_restore_delay_ms
        self.injector.direct_typing_fallback = new_config.direct_typing_fallback

        self.hotkey_manager.update(new_config.hotkey_mode, new_config.active_hotkey)

        needs_reload = self.transcriber.configure(
            model_size=new_config.model_size,
            compute_type=new_config.compute_type,
            cpu_threads=new_config.cpu_threads,
            vad_filter=new_config.vad_filter,
            beam_size=new_config.beam_size,
            performance_profile=new_config.performance_profile,
            offline_only=new_config.offline_only,
        )
        if needs_reload:
            self.preload_model()
