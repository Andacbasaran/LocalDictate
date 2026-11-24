"""Offline speech-to-text engine powered by faster-whisper (adaptive INT8 CPU + Silero VAD)."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from faster_whisper import WhisperModel

from .audio import load_audio_file
from .hardware import (
    HardwareProfile,
    compute_runtime_tuning,
    detect_hardware_profile,
    select_compute_type_candidates,
)

logger = logging.getLogger(__name__)

# Model metadata used by Settings Model Manager and cache inspector
MODEL_INFO: Dict[str, Dict[str, str]] = {
    "tiny": {
        "label": "Tiny",
        "size": "~75 MB",
        "hf_fragment": "faster-whisper-tiny",
    },
    "base": {
        "label": "Base",
        "size": "~145 MB",
        "hf_fragment": "faster-whisper-base",
    },
    "small": {
        "label": "Small",
        "size": "~465 MB",
        "hf_fragment": "faster-whisper-small",
    },
    "medium": {
        "label": "Medium",
        "size": "~1.5 GB",
        "hf_fragment": "faster-whisper-medium",
    },
    "large-v3-turbo": {
        "label": "Large v3 Turbo",
        "size": "~1.6 GB",
        "hf_fragment": "faster-whisper-large-v3-turbo",
    },
}


def get_hf_cache_dir() -> Path:
    """Return the Hugging Face hub cache directory used by faster-whisper."""
    hf_hub = os.environ.get("HF_HUB_CACHE")
    if hf_hub:
        return Path(hf_hub)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_model_cached(model_size: str, cache_dir: Optional[Path] = None) -> bool:
    """Return True if a faster-whisper (CTranslate2) model appears to be downloaded locally."""
    hub_dir = cache_dir or get_hf_cache_dir()
    if not hub_dir.is_dir():
        return False
    meta = MODEL_INFO.get(model_size)
    fragment = (meta["hf_fragment"] if meta else model_size).lower()
    try:
        for child in hub_dir.iterdir():
            if child.is_dir() and fragment in child.name.lower():
                snapshots = child / "snapshots"
                if snapshots.is_dir():
                    for snap in snapshots.iterdir():
                        if snap.is_dir() and (snap / "model.bin").exists():
                            return True
    except OSError:
        return False
    return False


def list_cached_models(cache_dir: Optional[Path] = None) -> List[str]:
    """Return the list of known Whisper model sizes currently present in local cache."""
    return [m for m in MODEL_INFO if is_model_cached(m, cache_dir=cache_dir)]


@dataclass
class TranscriptionResult:
    text: str
    language: str
    duration_sec: float
    inference_sec: float
    task: str = "transcribe"
    compute_type: str = "int8"
    backend: str = "faster-whisper"


class WhisperTranscriber:
    """Thread-safe wrapper around faster-whisper running on CPU (0 MB VRAM) with adaptive fallback."""

    def __init__(
        self,
        model_size: str = "small",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        vad_filter: bool = True,
        beam_size: int = 5,
        performance_profile: str = "auto",
        hw_profile: Optional[HardwareProfile] = None,
        local_files_only: bool = False,
    ) -> None:
        self.model_size = model_size
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.vad_filter = vad_filter
        self.beam_size = beam_size
        self.performance_profile = performance_profile
        self._hw_profile = hw_profile
        self.local_files_only = local_files_only

        self._model: WhisperModel | None = None
        self._lock = threading.Lock()
        self._loaded_key: tuple[str, str, int] | None = None
        self._active_compute_type: str = compute_type
        self._active_threads: int = cpu_threads
        self._active_backend: str = "faster-whisper"

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def active_compute_type(self) -> str:
        return self._active_compute_type

    @property
    def active_threads(self) -> int:
        return self._active_threads

    @property
    def active_backend(self) -> str:
        return self._active_backend

    def _resolve_tuning(self) -> tuple[int, tuple[str, ...]]:
        hw = self._hw_profile or detect_hardware_profile(query_ct2=True)
        self._hw_profile = hw
        tuning = compute_runtime_tuning(
            hw,
            requested_profile=self.performance_profile,
            preferred_compute_type=self.compute_type,
        )
        threads = self.cpu_threads if self.cpu_threads > 0 else tuning.whisper_threads
        candidates = select_compute_type_candidates(
            hw.supported_ct2_types,
            preferred=self.compute_type,
        )
        return threads, candidates

    def load(self) -> None:
        """Load (or reload) the Whisper model into RAM with safe compute_type fallback."""
        threads, candidates = self._resolve_tuning()
        target_key = (self.model_size, self.compute_type, threads)
        with self._lock:
            if self._model is not None and self._loaded_key == target_key:
                return

            last_exc: Exception | None = None
            for ctype in candidates:
                logger.info(
                    "Loading faster-whisper model=%s compute_type=%s cpu_threads=%s",
                    self.model_size,
                    ctype,
                    threads,
                )
                t0 = time.perf_counter()
                try:
                    self._model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type=ctype,
                        cpu_threads=threads,
                        local_files_only=self.local_files_only,
                    )
                    self._active_compute_type = ctype
                    self._active_threads = threads
                    self._active_backend = "faster-whisper"
                    self._loaded_key = target_key
                    logger.info(
                        "Model %s loaded in %.2fs (compute_type=%s, threads=%d)",
                        self.model_size,
                        time.perf_counter() - t0,
                        ctype,
                        threads,
                    )
                    return
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "compute_type=%s failed for model=%s (%s); trying next fallback...",
                        ctype,
                        self.model_size,
                        exc,
                    )

            raise RuntimeError(
                f"Failed to load Whisper model '{self.model_size}' with compute types {candidates}: {last_exc}"
            ) from last_exc

    def configure(
        self,
        model_size: str,
        compute_type: str = "int8",
        cpu_threads: int = 0,
        vad_filter: bool = True,
        beam_size: int = 5,
        performance_profile: str = "auto",
    ) -> bool:
        """Update settings. Returns True if the model needs to be reloaded."""
        needs_reload = (
            model_size != self.model_size
            or compute_type != self.compute_type
            or cpu_threads != self.cpu_threads
            or performance_profile != self.performance_profile
        )
        self.model_size = model_size
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.vad_filter = vad_filter
        self.beam_size = beam_size
        self.performance_profile = performance_profile
        if needs_reload:
            with self._lock:
                self._model = None
                self._loaded_key = None
        return needs_reload

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = "auto",
        initial_prompt: str | None = None,
        task: str = "transcribe",
    ) -> TranscriptionResult:
        """Transcribe (or translate to English when task='translate') a 16 kHz mono float32 array."""
        if audio.size == 0:
            return TranscriptionResult(
                text="",
                language="",
                duration_sec=0.0,
                inference_sec=0.0,
                task=task,
                compute_type=self._active_compute_type,
                backend=self._active_backend,
            )

        duration_sec = audio.size / 16_000.0
        if duration_sec < 0.2:
            return TranscriptionResult(
                text="",
                language="",
                duration_sec=duration_sec,
                inference_sec=0.0,
                task=task,
                compute_type=self._active_compute_type,
                backend=self._active_backend,
            )

        if self._model is None:
            self.load()

        lang_arg = None if not language or language == "auto" else language
        task_arg = "translate" if task == "translate" else "transcribe"

        t0 = time.perf_counter()
        with self._lock:
            assert self._model is not None
            segments, info = self._model.transcribe(
                audio,
                language=lang_arg,
                task=task_arg,
                initial_prompt=initial_prompt or None,
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
            task=task_arg,
            compute_type=self._active_compute_type,
            backend=self._active_backend,
        )

    def transcribe_file(
        self,
        file_path: Path | str,
        language: str = "auto",
        initial_prompt: str | None = None,
        task: str = "transcribe",
    ) -> TranscriptionResult:
        """Decode an offline audio file (.wav/.mp3/.m4a/.flac/.ogg) and transcribe it."""
        audio, _duration = load_audio_file(file_path)
        return self.transcribe(
            audio,
            language=language,
            initial_prompt=initial_prompt,
            task=task,
        )
