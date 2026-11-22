"""Text post-processing: hallucination filtering, dictionary replacements, and Ollama LLM refinement."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import AppConfig

logger = logging.getLogger(__name__)

# Common Whisper silence/outro hallucination phrases (lowercase, stripped of punctuation)
HALLUCINATION_PHRASES: set[str] = {
    "altyazı m.k",
    "altyazı mk",
    "izlediğiniz için teşekkürler",
    "izlediğiniz için teşekkür ederim",
    "abone olmayı unutmayın",
    "kanalıma abone olmayı unutmayın",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "subtitles by the amara.org community",
    "you",
}

STYLE_SYSTEM_PROMPTS: dict[str, str] = {
    "cleanup": (
        "Sen bir sesli dikte düzenleyicisisin. Verilen konuşma metnini yalnızca noktalama, "
        "büyük/küçük harf ve yazım açısından düzelt; 'eee', 'ııı', 'şey' gibi dolgu seslerini temizle. "
        "Metnin dilini (Türkçe veya İngilizce) ve anlamını ASLA değiştirme, yorum ekleme, "
        "yalnızca temizlenmiş metni döndür."
    ),
    "formal": (
        "Sen bir profesyonel editörsün. Verilen dikte metnini anlamını ve dilini koruyarak "
        "daha kurumsal, akıcı ve e-posta/iş yazışmasına uygun hale getir. "
        "Açıklama yapma, yalnızca düzenlenmiş metni döndür."
    ),
    "concise": (
        "Verilen dikte metnini dilini ve ana fikrini koruyarak gereksiz tekrarlardan arındır, "
        "kısa ve net hale getir. Yalnızca düzenlenmiş metni döndür."
    ),
    "code": (
        "Sen teknik bir dikte düzenleyicisisin. Verilen metindeki noktalama ve imlayı düzeltirken "
        "İngilizce yazılım, API, kütüphane ve kod terimlerini olduğu gibi koru. "
        "Açıklama yapma, yalnızca düzenlenmiş metni döndür."
    ),
}


@dataclass
class PostProcessResult:
    raw_text: str
    final_text: str
    used_llm: bool = False
    llm_error: str | None = None


def is_hallucination(text: str) -> bool:
    """Detect common Whisper hallucination strings produced on near-silent audio."""
    normalized = re.sub(r"[^\w\s.]", "", text.lower()).strip().rstrip(".")
    return normalized in HALLUCINATION_PHRASES


def normalize_spacing(text: str) -> str:
    """Collapse extra whitespace and fix spacing around punctuation."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return cleaned


def apply_replacements(text: str, replacements: dict[str, str]) -> str:
    """Apply case-insensitive whole-word/phrase dictionary replacements."""
    if not text or not replacements:
        return text

    result = text
    # Sort longest-first so multi-word snippets match before shorter sub-words
    for src, dst in sorted(replacements.items(), key=lambda kv: len(kv[0]), reverse=True):
        src_clean = src.strip()
        if not src_clean:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(src_clean)}(?!\w)", re.IGNORECASE)
        result = pattern.sub(dst, result)
    return result


def fetch_ollama_models(base_url: str, timeout: float = 3.0) -> list[str]:
    """Query a local Ollama server for installed model names."""
    url = f"{base_url.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    models = payload.get("models", [])
    return [m["name"] for m in models if isinstance(m, dict) and "name" in m]


def refine_with_ollama(
    text: str,
    base_url: str,
    model: str,
    style: str = "cleanup",
    timeout: float = 8.0,
) -> str:
    """Send transcribed text to local Ollama /api/generate for punctuation & cleanup."""
    system_prompt = STYLE_SYSTEM_PROMPTS.get(style, STYLE_SYSTEM_PROMPTS["cleanup"])
    url = f"{base_url.rstrip('/')}/api/generate"
    body = json.dumps({
        "model": model,
        "system": system_prompt,
        "prompt": text,
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    refined = str(payload.get("response", "")).strip()
    # Strip wrapping quotes if the LLM added them
    if len(refined) >= 2 and refined[0] == refined[-1] and refined[0] in ('"', "'"):
        refined = refined[1:-1].strip()
    return refined or text


class TextPostProcessor:
    """Runs deterministic cleanup + dictionary replacements + optional Ollama refinement."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def process(self, raw_text: str) -> PostProcessResult:
        cleaned = normalize_spacing(raw_text)
        if not cleaned or is_hallucination(cleaned):
            return PostProcessResult(raw_text=raw_text, final_text="", used_llm=False)

        cleaned = apply_replacements(cleaned, self.config.replacements)

        used_llm = False
        llm_error: str | None = None

        if self.config.ollama_enabled and self.config.ollama_model.strip():
            try:
                refined = refine_with_ollama(
                    text=cleaned,
                    base_url=self.config.ollama_url,
                    model=self.config.ollama_model.strip(),
                    style=self.config.ollama_style,
                    timeout=self.config.ollama_timeout_sec,
                )
                if refined:
                    cleaned = normalize_spacing(refined)
                    used_llm = True
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                llm_error = str(exc)
                logger.warning("Ollama post-processing unavailable, falling back to raw text: %s", exc)

        if self.config.append_trailing_space and cleaned:
            cleaned = f"{cleaned} "

        return PostProcessResult(
            raw_text=raw_text,
            final_text=cleaned,
            used_llm=used_llm,
            llm_error=llm_error,
        )
