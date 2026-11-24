"""Text post-processing: hallucination filtering, voice commands, snippets, and local/BYOK LLM refinement."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional

from .config import AppConfig
from .snippets import apply_replacements, apply_voice_commands

logger = logging.getLogger(__name__)

LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# Common Whisper silence/outro hallucination phrases (lowercase, stripped of punctuation)
HALLUCINATION_PHRASES: set[str] = {
    "altyazı m.k",
    "altyazı mk",
    "altyazi mk",
    "izlediğiniz için teşekkürler",
    "izlediğiniz için teşekkür ederim",
    "abone olmayı unutmayın",
    "kanalıma abone olmayı unutmayın",
    "beğenmeyi ve abone olmayı unutmayın",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "subtitles by the amara.org community",
    "amara.org",
    "you",
    "thank you",
    "mbc",
}

STYLE_SYSTEM_PROMPTS_EN: Dict[str, str] = {
    "cleanup": (
        "You are a precision voice dictation editor. Fix punctuation, capitalization, and spelling, "
        "and remove filler words ('um', 'uh', 'like', 'you know'). Preserve the original language, "
        "meaning, and tone strictly. Never add commentary or quotes—return only the cleaned text."
    ),
    "formal": (
        "You are a professional business editor. Rewrite the dictated text into clear, polite, "
        "email-ready professional prose while preserving the original language and meaning. "
        "Return only the revised text with no preamble."
    ),
    "concise": (
        "Tighten the dictated text by removing repetition and filler so it is crisp and direct, "
        "preserving its original language and core message. Return only the tightened text."
    ),
    "code": (
        "You are a technical dictation editor for software engineers. Fix punctuation and grammar "
        "while preserving programming identifiers, APIs, CLI flags, library names, and technical "
        "terms verbatim (e.g., camelCase, snake_case, C++, FastAPI, PyQt6). Return only the edited text."
    ),
    "bullet_notes": (
        "Convert the dictated thoughts into clean, concise Markdown bullet points (`- ...`), "
        "preserving the original language and every key detail. Return only the bullet list."
    ),
    "git_commit": (
        "Convert the dictated description into a crisp Conventional Commit message "
        "(e.g., `feat(scope): summary` or `fix(scope): summary`) in imperative mood. "
        "Return only the commit message with no markdown code fences."
    ),
    "translate_en": (
        "Translate the dictated text accurately into natural, fluent English with clean punctuation. "
        "Return only the English translation with no commentary."
    ),
}

STYLE_SYSTEM_PROMPTS_TR: Dict[str, str] = {
    "cleanup": (
        "Sen bir sesli dikte düzenleyicisisin. Verilen konuşma metnini yalnızca noktalama, "
        "büyük/küçük harf ve yazım açısından düzelt; 'eee', 'ııı', 'şey' gibi dolgu seslerini temizle. "
        "Metnin dilini ve anlamını ASLA değiştirme, yorum ekleme, yalnızca temizlenmiş metni döndür."
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
        "yazılım, API, kütüphane, dosya yolu ve kod terimlerini (ör. C++, PyQt6, FastAPI) olduğu gibi koru. "
        "Açıklama yapma, yalnızca düzenlenmiş metni döndür."
    ),
    "bullet_notes": (
        "Verilen sesli notları dilini ve ana fikirlerini koruyarak düzenli Markdown madde işaretlerine "
        "(`- ...`) dönüştür. Yalnızca madde listesini döndür."
    ),
    "git_commit": (
        "Verilen açıklamayı temiz bir Conventional Commit mesajına (ör. `feat(ui): ...` veya `fix(audio): ...`) "
        "dönüştür. Kod bloğu veya açıklama eklemeden yalnızca commit mesajını döndür."
    ),
    "translate_en": (
        "Verilen metni anlamını koruyarak doğal, akıcı ve doğru noktalama işaretleriyle İngilizceye çevir. "
        "Açıklama yapma, yalnızca İngilizce çeviriyi döndür."
    ),
}

# Backwards-compatible reference for v0.2.0 imports
STYLE_SYSTEM_PROMPTS = STYLE_SYSTEM_PROMPTS_EN


class OfflineLockError(RuntimeError):
    """Raised when Offline Lock blocks an outbound non-localhost LLM request."""


@dataclass
class PostProcessResult:
    raw_text: str
    final_text: str
    used_llm: bool = False
    llm_error: str | None = None
    llm_sec: float = 0.0
    mode_used: str = "cleanup"


def is_localhost_url(url: str) -> bool:
    """Return True if the given HTTP(S) URL points strictly to the local machine."""
    try:
        parsed = urllib.parse.urlparse((url or "").strip())
        host = (parsed.hostname or "").strip().lower()
        return host in LOCALHOST_HOSTS
    except Exception:
        return False


def select_system_prompt(
    style: str,
    language: str = "en",
    custom_prompts: Optional[Dict[str, str]] = None,
) -> str:
    """Resolve the best language-aware system prompt for a dictation mode."""
    mode = (style or "cleanup").strip().lower()
    if custom_prompts and custom_prompts.get(mode, "").strip():
        return custom_prompts[mode].strip()

    lang_low = (language or "").strip().lower()
    if lang_low == "tr" and mode != "translate_en":
        return STYLE_SYSTEM_PROMPTS_TR.get(mode, STYLE_SYSTEM_PROMPTS_TR["cleanup"])
    return STYLE_SYSTEM_PROMPTS_EN.get(mode, STYLE_SYSTEM_PROMPTS_EN["cleanup"])


def is_hallucination(text: str) -> bool:
    """Detect common Whisper hallucination strings produced on near-silent audio."""
    normalized = re.sub(r"[^\w\s.]", "", text.lower()).strip().rstrip(".")
    return normalized in HALLUCINATION_PHRASES


def normalize_spacing(text: str) -> str:
    """Collapse extra horizontal whitespace and fix spacing around punctuation, preserving newlines."""
    if not text:
        return ""
    lines = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", raw_line).strip()
        cleaned = re.sub(r"[ \t]+([,.;:!?])", r"\1", cleaned)
        lines.append(cleaned)
    joined = "\n".join(lines)
    # Collapse 3+ consecutive newlines to 2
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def _strip_llm_wrappers(text: str) -> str:
    refined = (text or "").strip()
    if len(refined) >= 2 and refined[0] == refined[-1] and refined[0] in ('"', "'"):
        refined = refined[1:-1].strip()
    return refined


def fetch_ollama_models(base_url: str, timeout: float = 3.0) -> list[str]:
    """Query a local Ollama server for installed model names."""
    url = f"{base_url.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    models = payload.get("models", [])
    return [m["name"] for m in models if isinstance(m, dict) and "name" in m]


def fetch_openai_compat_models(
    base_url: str,
    api_key: str = "",
    timeout: float = 3.0,
) -> list[str]:
    """Query an OpenAI-compatible server (LM Studio, llama.cpp, vLLM, etc.) for model IDs."""
    root = base_url.rstrip("/")
    url = f"{root}/models" if root.endswith("/v1") else f"{root}/v1/models"
    headers = {"Accept": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload.get("data", [])
    return [m["id"] for m in data if isinstance(m, dict) and "id" in m]


def fetch_llm_models(
    backend: str,
    base_url: str,
    api_key: str = "",
    offline_only: bool = True,
    timeout: float = 3.0,
) -> list[str]:
    """Fetch available LLM models while respecting the Air-Gapped Offline Lock."""
    if offline_only and not is_localhost_url(base_url):
        raise OfflineLockError(
            "Air-Gapped Offline Lock is active: only localhost endpoints are permitted."
        )
    if backend == "openai_compat":
        return fetch_openai_compat_models(base_url=base_url, api_key=api_key, timeout=timeout)
    return fetch_ollama_models(base_url=base_url, timeout=timeout)


def refine_with_ollama(
    text: str,
    base_url: str,
    model: str,
    style: str = "cleanup",
    timeout: float = 8.0,
    language: str = "en",
    custom_prompts: Optional[Dict[str, str]] = None,
) -> str:
    """Send transcribed text to local Ollama /api/generate for punctuation & style refinement."""
    system_prompt = select_system_prompt(style, language=language, custom_prompts=custom_prompts)
    url = f"{base_url.rstrip('/')}/api/generate"
    body = json.dumps(
        {
            "model": model,
            "system": system_prompt,
            "prompt": text,
            "stream": False,
            "options": {"temperature": 0.1},
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    refined = _strip_llm_wrappers(str(payload.get("response", "")))
    return refined or text


def refine_with_openai_compat(
    text: str,
    base_url: str,
    model: str,
    style: str = "cleanup",
    api_key: str = "",
    timeout: float = 8.0,
    language: str = "en",
    custom_prompts: Optional[Dict[str, str]] = None,
) -> str:
    """Send transcribed text to an OpenAI-compatible chat completions endpoint (LM Studio / llama.cpp)."""
    system_prompt = select_system_prompt(style, language=language, custom_prompts=custom_prompts)
    root = base_url.rstrip("/")
    url = f"{root}/chat/completions" if root.endswith("/v1") else f"{root}/v1/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    body = json.dumps(
        {
            "model": model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        }
    ).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    choices = payload.get("choices") or []
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        refined = _strip_llm_wrappers(str(msg.get("content", "")))
        if refined:
            return refined
    return text


class TextPostProcessor:
    """Runs hallucination filtering, voice commands, snippets/dictionary, and optional local/BYOK LLM."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def process(
        self,
        raw_text: str,
        mode: Optional[str] = None,
        detected_language: str = "",
    ) -> PostProcessResult:
        active_mode = (mode or self.config.effective_style or "cleanup").strip().lower()
        cleaned = normalize_spacing(raw_text)
        if not cleaned or is_hallucination(cleaned):
            return PostProcessResult(
                raw_text=raw_text,
                final_text="",
                used_llm=False,
                mode_used=active_mode,
            )

        if self.config.voice_commands_enabled:
            cleaned = apply_voice_commands(cleaned)

        combined_rules: Dict[str, str] = {}
        if self.config.snippets:
            combined_rules.update(self.config.snippets)
        if self.config.replacements:
            combined_rules.update(self.config.replacements)

        if combined_rules:
            cleaned = apply_replacements(cleaned, combined_rules)

        used_llm = False
        llm_error: str | None = None
        llm_sec = 0.0

        # Resolve effective prompt language (detected_language > config.language > 'en')
        prompt_lang = detected_language or (
            self.config.language if self.config.language != "auto" else "en"
        )

        if self.config.ollama_enabled and self.config.ollama_model.strip():
            t0 = time.perf_counter()
            try:
                if self.config.offline_only and not is_localhost_url(self.config.ollama_url):
                    raise OfflineLockError(
                        "Air-Gapped Offline Lock blocked non-localhost LLM URL."
                    )

                if self.config.llm_backend == "openai_compat":
                    refined = refine_with_openai_compat(
                        text=cleaned,
                        base_url=self.config.ollama_url,
                        model=self.config.ollama_model.strip(),
                        style=active_mode,
                        api_key=self.config.llm_api_key,
                        timeout=self.config.ollama_timeout_sec,
                        language=prompt_lang,
                        custom_prompts=self.config.custom_mode_prompts,
                    )
                else:
                    refined = refine_with_ollama(
                        text=cleaned,
                        base_url=self.config.ollama_url,
                        model=self.config.ollama_model.strip(),
                        style=active_mode,
                        timeout=self.config.ollama_timeout_sec,
                        language=prompt_lang,
                        custom_prompts=self.config.custom_mode_prompts,
                    )
                llm_sec = time.perf_counter() - t0
                if refined:
                    cleaned = normalize_spacing(refined)
                    used_llm = True
            except (
                OfflineLockError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
                json.JSONDecodeError,
            ) as exc:
                llm_sec = time.perf_counter() - t0
                llm_error = str(exc)
                logger.warning("Local LLM post-processing unavailable, using raw text: %s", exc)

        if self.config.append_trailing_space and cleaned:
            cleaned = f"{cleaned} "

        return PostProcessResult(
            raw_text=raw_text,
            final_text=cleaned,
            used_llm=used_llm,
            llm_error=llm_error,
            llm_sec=llm_sec,
            mode_used=active_mode,
        )
