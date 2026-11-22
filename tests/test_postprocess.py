"""Tests for text post-processing, hallucination filtering, dictionary replacements, and Ollama fallback."""

from unittest.mock import patch

from localdictate.config import AppConfig
from localdictate.postprocess import (
    TextPostProcessor,
    apply_replacements,
    is_hallucination,
    normalize_spacing,
)


def test_hallucination_detection():
    assert is_hallucination("Altyazı M.K.")
    assert is_hallucination("  Thanks for watching! ")
    assert is_hallucination("Abone olmayı unutmayın.")
    assert not is_hallucination("Bugün toplantı saat üçte.")


def test_normalize_spacing():
    assert normalize_spacing("  Merhaba   dünya , nasılsın ? ") == "Merhaba dünya, nasılsın?"


def test_apply_replacements_whole_word_and_longest_first():
    rules = {
        "visper": "Wispr",
        "lokal dikteyt": "LocalDictate",
        "imzam": "Saygılarımla, Andaç",
    }
    text = "visper yerine lokal dikteyt kullanıyorum, imzam."
    assert apply_replacements(text, rules) == "Wispr yerine LocalDictate kullanıyorum, Saygılarımla, Andaç."


def test_postprocessor_drops_hallucinations():
    proc = TextPostProcessor(AppConfig())
    res = proc.process("Altyazı M.K.")
    assert res.final_text == ""
    assert not res.used_llm


def test_postprocessor_ollama_success_and_graceful_fallback():
    cfg = AppConfig(ollama_enabled=True, ollama_model="qwen2.5:3b", append_trailing_space=True)
    proc = TextPostProcessor(cfg)

    with patch("localdictate.postprocess.refine_with_ollama", return_value="Merhaba, nasılsın?"):
        res = proc.process("merhaba nasılsın")
        assert res.used_llm is True
        assert res.final_text == "Merhaba, nasılsın? "
        assert res.llm_error is None

    with patch("localdictate.postprocess.refine_with_ollama", side_effect=TimeoutError("timeout")):
        res = proc.process("merhaba dünya")
        assert res.used_llm is False
        assert res.final_text == "merhaba dünya "
        assert res.llm_error is not None
