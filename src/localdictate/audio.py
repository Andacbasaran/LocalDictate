"""Resilient microphone audio capture, sample-rate negotiation, resampling, VAD, and offline audio loading."""

from __future__ import annotations

import logging
import math
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHANNELS = 1
BLOCK_MS = 64  # ~64ms chunks


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


def compute_rms_level(chunk: np.ndarray) -> float:
    """Compute perceptually mapped RMS level in [0.0, 1.0]."""
    if chunk.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float32))))
    return min(1.0, max(0.0, math.log1p(rms * 25.0) / math.log1p(25.0 * 0.25)))


def resample_audio(
    audio: np.ndarray,
    orig_sr: int,
    target_sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """Resample 1D float32 audio cleanly from orig_sr to target_sr."""
    arr = np.asarray(audio, dtype=np.float32).reshape(-1)
    if arr.size == 0 or orig_sr <= 0 or orig_sr == target_sr:
        return arr

    try:
        from scipy.signal import resample_poly

        g = math.gcd(int(orig_sr), int(target_sr))
        up = int(target_sr) // g
        down = int(orig_sr) // g
        resampled = resample_poly(arr, up, down).astype(np.float32, copy=False)
        return resampled
    except Exception:
        # Pure-numpy linear interpolation fallback
        duration = arr.size / float(orig_sr)
        new_len = max(1, int(round(duration * target_sr)))
        x_old = np.linspace(0.0, 1.0, arr.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, new_len, endpoint=False)
        return np.interp(x_new, x_old, arr).astype(np.float32)


def detect_speech_segments(
    audio: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    frame_ms: int = 30,
    threshold_rms: float = 0.012,
    pad_frames: int = 3,
) -> tuple[np.ndarray, float]:
    """Fast energy-based VAD that trims leading/trailing silence and returns (trimmed_audio, speech_ratio)."""
    arr = np.asarray(audio, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return arr, 0.0

    frame_len = max(1, int(sample_rate * frame_ms / 1000))
    n_frames = max(1, arr.size // frame_len)
    trimmed_len = n_frames * frame_len
    frames = arr[:trimmed_len].reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    voiced = rms >= threshold_rms
    speech_ratio = float(np.mean(voiced))

    indices = np.flatnonzero(voiced)
    if indices.size == 0:
        return arr, 0.0

    start_f = max(0, int(indices[0]) - pad_frames)
    end_f = min(n_frames, int(indices[-1]) + pad_frames + 1)
    return arr[start_f * frame_len : end_f * frame_len], speech_ratio


def load_audio_file(path: Path | str, target_sr: int = SAMPLE_RATE) -> tuple[np.ndarray, float]:
    """Decode an offline audio file (.wav, .mp3, .m4a, .flac, .ogg) into 16 kHz mono float32."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")

    # Fast stdlib path for uncompressed PCM WAV files
    if p.suffix.lower() == ".wav":
        try:
            with wave.open(str(p), "rb") as wf:
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                sr = wf.getframerate()
                raw = wf.readframes(wf.getnframes())
            if sampwidth == 2:
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            elif sampwidth == 4:
                samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
            elif sampwidth == 1:
                samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            else:
                raise ValueError(f"Unsupported WAV sample width: {sampwidth}")
            if n_channels > 1:
                samples = samples.reshape(-1, n_channels).mean(axis=1)
            resampled = resample_audio(samples, sr, target_sr)
            return resampled, resampled.size / float(target_sr)
        except Exception:
            # Fall through to PyAV for IEEE float WAV or non-PCM codecs
            pass

    # Offline PyAV (bundled with faster-whisper) supports MP3, M4A, FLAC, OGG, WAV, etc.
    try:
        import av

        chunks: list[np.ndarray] = []
        with av.open(str(p)) as container:
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=target_sr)
            for frame in container.decode(audio=0):
                out_frames = resampler.resample(frame)
                if not isinstance(out_frames, list):
                    out_frames = [out_frames]
                for of in out_frames:
                    arr = of.to_ndarray()
                    chunks.append(arr.reshape(-1).astype(np.float32, copy=False))
        if not chunks:
            return np.zeros(0, dtype=np.float32), 0.0
        audio = np.concatenate(chunks, axis=0)
        return audio, audio.size / float(target_sr)
    except Exception as exc:
        raise RuntimeError(f"Failed to decode audio file '{p.name}': {exc}") from exc


def _candidate_sample_rates(device: Optional[int]) -> list[int]:
    """Build deduplicated sample rate preference list for resilient microphone opening."""
    candidates: list[int] = [SAMPLE_RATE]
    try:
        info = sd.query_devices(device, "input")
        default_sr = int(round(float(info.get("default_samplerate", 0) or 0)))
        if default_sr > 0 and default_sr not in candidates:
            candidates.append(default_sr)
    except Exception:
        pass
    for sr in (48_000, 44_100, 32_000, 24_000):
        if sr not in candidates:
            candidates.append(sr)
    return candidates


class AudioRecorder:
    """Resilient microphone capture that negotiates device-native sample rate and resamples to 16 kHz.

    Never invokes Qt signals inside the PortAudio C callback thread; RMS levels are buffered
    atomically for UI polling via `get_latest_level()` and `get_waveform_snapshot()`.
    """

    def __init__(
        self,
        device: int | None = None,
        on_level: Callable[[float], None] | None = None,
        max_duration_sec: float = 300.0,
        silence_auto_stop_sec: float = 0.0,
        silence_threshold: float = 0.04,
        on_auto_stop: Callable[[str], None] | None = None,
    ) -> None:
        self.device = device
        self.on_level = on_level
        self.max_duration_sec = max(5.0, float(max_duration_sec))
        self.silence_auto_stop_sec = max(0.0, float(silence_auto_stop_sec))
        self.silence_threshold = float(silence_threshold)
        self.on_auto_stop = on_auto_stop

        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._recording = False
        self._capture_sr: int = SAMPLE_RATE
        self._record_start_mono: float = 0.0
        self._has_heard_speech: bool = False
        self._last_speech_mono: float = 0.0
        self._auto_stop_triggered: bool = False

        # Lock-free / atomic level buffer read by Qt main-thread QTimer
        self._latest_level: float = 0.0
        self._level_history: deque[float] = deque([0.0] * 24, maxlen=24)

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def capture_sample_rate(self) -> int:
        return self._capture_sr

    def get_latest_level(self) -> float:
        """Read the latest perceptual RMS level [0.0, 1.0] safely from any thread."""
        return self._latest_level

    def get_waveform_snapshot(self, bars: int = 24) -> list[float]:
        """Return a thread-safe snapshot of recent RMS levels for live waveform rendering."""
        with self._lock:
            vals = list(self._level_history)
        if len(vals) >= bars:
            return vals[-bars:]
        return ([0.0] * (bars - len(vals))) + vals

    def start(self) -> None:
        """Start capturing microphone audio, negotiating device-native sample rate if needed."""
        with self._lock:
            if self._recording:
                return
            self._chunks = []
            self._latest_level = 0.0
            self._level_history.clear()
            self._level_history.extend([0.0] * 24)
            self._has_heard_speech = False
            self._auto_stop_triggered = False

        last_exc: Exception | None = None
        stream: sd.InputStream | None = None
        chosen_sr = SAMPLE_RATE

        for sr in _candidate_sample_rates(self.device):
            blocksize = max(256, int(round(sr * BLOCK_MS / 1000.0)))
            try:
                stream = sd.InputStream(
                    samplerate=sr,
                    channels=CHANNELS,
                    dtype="float32",
                    blocksize=blocksize,
                    device=self.device,
                    callback=self._audio_callback,
                )
                stream.start()
                chosen_sr = sr
                break
            except Exception as exc:
                last_exc = exc
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None

        if stream is None:
            raise RuntimeError(f"Could not open microphone stream: {last_exc}") from last_exc

        now = time.monotonic()
        with self._lock:
            self._stream = stream
            self._capture_sr = chosen_sr
            self._record_start_mono = now
            self._last_speech_mono = now
            self._recording = True
        logger.info("Microphone recording started at %d Hz (device=%s)", chosen_sr, self.device)

    def stop(self) -> tuple[np.ndarray, float]:
        """Stop capturing, resample to 16 kHz mono float32, and return (audio, duration_sec)."""
        with self._lock:
            stream = self._stream
            self._stream = None
            self._recording = False
            capture_sr = self._capture_sr

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        with self._lock:
            if not self._chunks:
                self._latest_level = 0.0
                return np.zeros(0, dtype=np.float32), 0.0
            raw_audio = np.concatenate(self._chunks, axis=0).reshape(-1)
            self._chunks = []
            self._latest_level = 0.0

        audio = resample_audio(raw_audio, capture_sr, SAMPLE_RATE)
        duration = audio.size / float(SAMPLE_RATE)
        return audio, duration

    def cancel(self) -> None:
        """Abort recording and discard captured audio."""
        self.stop()

    def _trigger_auto_stop(self, reason: str) -> None:
        cb = self.on_auto_stop
        if cb is not None:
            # Dispatch off the PortAudio C callback thread to prevent deadlocks
            threading.Thread(target=cb, args=(reason,), daemon=True).start()

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        chunk = indata.copy()
        level = compute_rms_level(chunk)
        now = time.monotonic()
        auto_stop_reason: str | None = None

        with self._lock:
            if not self._recording:
                return
            self._chunks.append(chunk)
            self._latest_level = level
            self._level_history.append(level)

            elapsed = now - self._record_start_mono
            if not self._auto_stop_triggered:
                if elapsed >= self.max_duration_sec:
                    self._auto_stop_triggered = True
                    auto_stop_reason = "max_duration"
                elif self.silence_auto_stop_sec > 0.0:
                    if level >= self.silence_threshold:
                        self._has_heard_speech = True
                        self._last_speech_mono = now
                    elif (
                        self._has_heard_speech
                        and (now - self._last_speech_mono) >= self.silence_auto_stop_sec
                    ):
                        self._auto_stop_triggered = True
                        auto_stop_reason = "silence"

        if auto_stop_reason is not None:
            self._trigger_auto_stop(auto_stop_reason)

        if self.on_level is not None:
            try:
                self.on_level(level)
            except Exception:
                pass
