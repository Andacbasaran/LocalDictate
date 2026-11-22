"""Offline speech-to-text engine powered by faster-whisper (INT8 CPU + Silero VAD)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str
    duration_sec: float
    inference_sec: float


class WhisperTranscriber:
    """Thread-safe wrapper around faster-whisper running on CPU (0 MB VRAM)."""

    def __init__(
        self,
        model_size: str = "small",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        vad_filter: bool = True,
        beam_size: int = 5,
    ) -> None:
        self.model_size = model_size
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.vad_filter = vad_filter
        self.beam_size = beam_size

        self._model: WhisperModel | None = None
        self._lock = threading.Lock()
        self._loaded_key: tuple[str, str, int] | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load (or reload) the Whisper model into RAM."""
        target_key = (self.model_size, self.compute_type, self.cpu_threads)
        with self._lock:
            if self._model is not None and self._loaded_key == target_key:
                return
            logger.info(
                "Loading faster-whisper model=%s compute_type=%s cpu_threads=%s",
                self.model_size,
                self.compute_type,
                self.cpu_threads,
            )
            t0 = time.perf_counter()
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
            )
            self._loaded_key = target_key
            logger.info("Model loaded in %.2fs", time.perf_counter() - t0)

    def configure(
        self,
        model_size: str,
        compute_type: str = "int8",
        cpu_threads: int = 0,
        vad_filter: bool = True,
        beam_size: int = 5,
    ) -> bool:
        """Update settings. Returns True if the model needs to be reloaded."""
        needs_reload = (
            model_size != self.model_size
            or compute_type != self.compute_type
            or cpu_threads != self.cpu_threads
        )
        self.model_size = model_size
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.vad_filter = vad_filter
        self.beam_size = beam_size
        if needs_reload:
            with self._lock:
                self._model = None
                self._loaded_key = None
        return needs_reload

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = "auto",
    ) -> TranscriptionResult:
        """Transcribe a 16 kHz mono float32 audio array."""
        if audio.size == 0:
            return TranscriptionResult(text="", language="", duration_sec=0.0, inference_sec=0.0)

        duration_sec = audio.size / 16_000.0
        if duration_sec < 0.2:
            return TranscriptionResult(text="", language="", duration_sec=duration_sec, inference_sec=0.0)

        if self._model is None:
            self.load()

        lang_arg = None if not language or language == "auto" else language

        t0 = time.perf_counter()
        with self._lock:
            assert self._model is not None
            segments, info = self._model.transcribe(
                audio,
                language=lang_arg,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        inference_sec = time.perf_counter() - t0

        text = " ".join(parts).strip()
        detected_lang = getattr(info, "language", "") or (lang_arg or "")
        return TranscriptionResult(
            text=text,
            language=detected_lang,
            duration_sec=duration_sec,
            inference_sec=inference_sec,
        )
