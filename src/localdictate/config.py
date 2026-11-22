"""Configuration management for LocalDictate."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


AVAILABLE_MODELS = [
    ("tiny", "Tiny (~75 MB — En hızlı, temel doğruluk)"),
    ("base", "Base (~145 MB — Çok hızlı)"),
    ("small", "Small (~465 MB — Önerilen, dengeli)"),
    ("medium", "Medium (~1.5 GB — Yüksek doğruluk)"),
    ("large-v3-turbo", "Large v3 Turbo (~1.6 GB — En yüksek doğruluk)"),
]

AVAILABLE_LANGUAGES = [
    ("auto", "Otomatik (TR / EN / Çoklu Dil)"),
    ("tr", "Türkçe"),
    ("en", "İngilizce"),
]

HOTKEY_MODES = [
    ("toggle", "Aç-Kapa (Toggle)"),
    ("push_to_talk", "Bas-Konuş (Push-to-Talk)"),
]

OLLAMA_STYLES = [
    ("cleanup", "Noktalama & Akıcılık (Dolgu kelimelerini temizle)"),
    ("formal", "Kurumsal / E-posta Tonu"),
    ("concise", "Kısa & Öz"),
    ("code", "Teknik / Kod Terimlerini Koru"),
]


def get_config_dir() -> Path:
    """Return the platform-appropriate configuration directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "LocalDictate"


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


def get_history_db_path() -> Path:
    return get_config_dir() / "history.db"


@dataclass
class AppConfig:
    # Hotkeys
    hotkey_mode: str = "toggle"  # "toggle" | "push_to_talk"
    toggle_hotkey: str = "ctrl+alt+space"
    ptt_hotkey: str = "ctrl_r"

    # Whisper STT
    model_size: str = "small"
    language: str = "auto"  # "auto" | "tr" | "en"
    compute_type: str = "int8"
    vad_filter: bool = True
    beam_size: int = 5
    cpu_threads: int = 0

    # Audio & UX
    input_device: int | None = None
    sound_effects: bool = True
    overlay_position: str = "bottom_center"  # "bottom_center" | "top_center"
    restore_clipboard: bool = True
    paste_delay_ms: int = 50
    append_trailing_space: bool = False
    save_history: bool = True
    launch_at_startup: bool = False

    # Personal Dictionary & Snippets
    custom_vocabulary: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)

    # Optional Local LLM (Ollama) Post-Processing
    ollama_enabled: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_style: str = "cleanup"  # "cleanup" | "formal" | "concise" | "code"
    ollama_timeout_sec: float = 8.0

    @property
    def active_hotkey(self) -> str:
        if self.hotkey_mode == "push_to_talk":
            return self.ptt_hotkey
        return self.toggle_hotkey

    def build_initial_prompt(self) -> str | None:
        """Build a Whisper initial_prompt biasing recognition toward custom vocabulary."""
        words = [w.strip() for w in self.custom_vocabulary if w.strip()]
        if not words:
            return None
        return ", ".join(words)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        valid_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_names}
        # Defensive type coercion for mutable fields
        if "custom_vocabulary" in filtered and not isinstance(filtered["custom_vocabulary"], list):
            filtered["custom_vocabulary"] = []
        if "replacements" in filtered and not isinstance(filtered["replacements"], dict):
            filtered["replacements"] = {}
        return cls(**filtered)


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from disk, returning defaults if missing or invalid."""
    cfg_path = path or get_config_path()
    if not cfg_path.exists():
        return AppConfig()
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AppConfig()
        return AppConfig.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Persist configuration to disk as formatted JSON."""
    cfg_path = path or get_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return cfg_path
