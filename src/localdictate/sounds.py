"""Subtle synthesized audio cues for start, stop, and error feedback."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

_SR = 24_000


def _synth_tone(freqs: list[tuple[float, float]], volume: float = 0.08) -> np.ndarray:
    """Synthesize a soft, click-free sequence of (frequency_hz, duration_sec) sine tones."""
    segments: list[np.ndarray] = []
    for freq, dur in freqs:
        n = max(1, int(_SR * dur))
        t = np.linspace(0.0, dur, n, endpoint=False, dtype=np.float32)
        wave = np.sin(2.0 * np.pi * freq * t) * volume
        # Smooth cosine fade-in / fade-out envelope (8ms) to avoid speaker clicks
        fade = min(n // 2, int(_SR * 0.008))
        if fade > 0:
            env = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            wave[:fade] *= env
            wave[-fade:] *= env[::-1]
        segments.append(wave.astype(np.float32))
    return np.concatenate(segments)


_CUE_START = _synth_tone([(587.33, 0.055), (880.0, 0.075)], volume=0.07)
_CUE_STOP = _synth_tone([(783.99, 0.055), (523.25, 0.075)], volume=0.065)
_CUE_ERROR = _synth_tone([(330.0, 0.09), (261.63, 0.12)], volume=0.07)


def _play_async(samples: np.ndarray) -> None:
    def _worker() -> None:
        try:
            sd.play(samples, samplerate=_SR, blocking=False)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def play_start_cue(enabled: bool = True) -> None:
    if enabled:
        _play_async(_CUE_START)


def play_stop_cue(enabled: bool = True) -> None:
    if enabled:
        _play_async(_CUE_STOP)


def play_error_cue(enabled: bool = True) -> None:
    if enabled:
        _play_async(_CUE_ERROR)
