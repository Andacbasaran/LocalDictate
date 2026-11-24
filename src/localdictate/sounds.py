"""Subtle synthesized audio cues for start, stop, and error feedback without mic bleed."""

from __future__ import annotations

import threading

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - headless CI without PulseAudio/PortAudio server
    sd = None  # type: ignore[assignment]

_SR = 24_000


def _synth_tone(freqs: list[tuple[float, float]], volume: float = 0.07) -> np.ndarray:
    """Synthesize a soft, click-free sequence of (frequency_hz, duration_sec) sine tones."""
    segments: list[np.ndarray] = []
    for freq, dur in freqs:
        n = max(1, int(_SR * dur))
        t = np.linspace(0.0, dur, n, endpoint=False, dtype=np.float32)
        wave = np.sin(2.0 * np.pi * freq * t) * volume
        fade = min(n // 2, int(_SR * 0.008))
        if fade > 0:
            env = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            wave[:fade] *= env
            wave[-fade:] *= env[::-1]
        segments.append(wave.astype(np.float32))
    return np.concatenate(segments)


# Crisp, short cues (~85ms) so start cue completes cleanly before microphone capture opens
_CUE_START = _synth_tone([(587.33, 0.038), (880.0, 0.048)], volume=0.06)
_CUE_STOP = _synth_tone([(783.99, 0.045), (523.25, 0.060)], volume=0.06)
_CUE_ERROR = _synth_tone([(330.0, 0.08), (261.63, 0.11)], volume=0.065)


def _play_samples(samples: np.ndarray, wait: bool = False, max_wait_sec: float = 0.16) -> None:
    if sd is None:
        return
    done = threading.Event()

    def _worker() -> None:
        try:
            sd.play(samples, samplerate=_SR, blocking=wait)
        except Exception:
            pass
        finally:
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    if wait:
        done.wait(timeout=max_wait_sec)


def play_start_cue(enabled: bool = True, wait: bool = True) -> None:
    """Play start cue. Waiting briefly (~90ms) prevents the chime leaking into the mic buffer."""
    if enabled:
        _play_samples(_CUE_START, wait=wait, max_wait_sec=0.14)


def play_stop_cue(enabled: bool = True) -> None:
    if enabled:
        _play_samples(_CUE_STOP, wait=False)


def play_error_cue(enabled: bool = True) -> None:
    if enabled:
        _play_samples(_CUE_ERROR, wait=False)
