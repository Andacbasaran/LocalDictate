"""Microphone audio capture with live RMS level metering."""

from __future__ import annotations

import math
import threading
from typing import Callable

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
CHANNELS = 1
BLOCK_SIZE = 1024  # ~64ms chunks at 16 kHz


def list_input_devices() -> list[tuple[int, str]]:
    """Return available audio input devices as (device_index, display_name)."""
    devices: list[tuple[int, str]] = []
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                hostapi = sd.query_hostapis(dev["hostapi"])["name"]
                devices.append((idx, f"{dev['name']} ({hostapi})"))
    except Exception:
        pass
    return devices


class AudioRecorder:
    """Captures 16 kHz mono float32 audio from the selected microphone."""

    def __init__(
        self,
        device: int | None = None,
        on_level: Callable[[float], None] | None = None,
    ) -> None:
        self.device = device
        self.on_level = on_level
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self) -> None:
        """Start capturing microphone audio."""
        with self._lock:
            if self._recording:
                return
            self._chunks = []
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                device=self.device,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._recording = True

    def stop(self) -> tuple[np.ndarray, float]:
        """Stop capturing and return (audio_float32_1d, duration_seconds)."""
        with self._lock:
            stream = self._stream
            self._stream = None
            self._recording = False

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32), 0.0
            audio = np.concatenate(self._chunks, axis=0).reshape(-1)
            self._chunks = []

        duration = len(audio) / float(SAMPLE_RATE)
        return audio, duration

    def cancel(self) -> None:
        """Abort recording and discard captured audio."""
        self.stop()

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        chunk = indata.copy()
        with self._lock:
            if not self._recording:
                return
            self._chunks.append(chunk)

        if self.on_level is not None:
            rms = float(np.sqrt(np.mean(chunk * chunk)))
            # Map RMS perceptually to [0.0, 1.0] for responsive UI bars
            level = min(1.0, max(0.0, math.log1p(rms * 25.0) / math.log1p(25.0 * 0.25)))
            try:
                self.on_level(level)
            except Exception:
                pass
