"""Tests for DictationController state machine."""

import time
from unittest.mock import MagicMock

import numpy as np

from localdictate.config import AppConfig
from localdictate.controller import AppState, DictationController
from localdictate.transcriber import TranscriptionResult


def _make_controller(duration: float = 1.0, text: str = "Merhaba dünya"):
    recorder = MagicMock()
    recorder.is_recording = False
    recorder.stop.return_value = (np.ones(int(16_000 * duration), dtype=np.float32), duration)

    transcriber = MagicMock()
    transcriber.transcribe.return_value = TranscriptionResult(
        text=text,
        language="tr",
        duration_sec=duration,
        inference_sec=0.42,
    )

    injector = MagicMock()
    hotkey_manager = MagicMock()

    controller = DictationController(
        config=AppConfig(),
        recorder=recorder,
        transcriber=transcriber,
        injector=injector,
        hotkey_manager=hotkey_manager,
    )
    return controller, recorder, transcriber, injector


def test_full_dictation_flow():
    controller, recorder, transcriber, injector = _make_controller(
        duration=1.2,
        text="Merhaba dünya",
    )
    assert controller.state == AppState.IDLE

    controller.start_recording()
    assert controller.state == AppState.RECORDING
    recorder.start.assert_called_once()

    controller.stop_recording()
    # Wait briefly for background transcription thread to finish
    deadline = time.monotonic() + 2.0
    while controller.state != AppState.IDLE and time.monotonic() < deadline:
        time.sleep(0.02)

    assert controller.state == AppState.IDLE
    transcriber.transcribe.assert_called_once()
    injector.inject.assert_called_once_with("Merhaba dünya")


def test_short_recording_skips_transcription():
    controller, recorder, transcriber, injector = _make_controller(duration=0.05)

    controller.start_recording()
    controller.stop_recording()

    assert controller.state == AppState.IDLE
    transcriber.transcribe.assert_not_called()
    injector.inject.assert_not_called()


def test_cancel_recording_returns_to_idle():
    controller, recorder, transcriber, injector = _make_controller()

    controller.start_recording()
    assert controller.state == AppState.RECORDING

    controller.cancel_recording()
    assert controller.state == AppState.IDLE
    recorder.cancel.assert_called_once()
    transcriber.transcribe.assert_not_called()
