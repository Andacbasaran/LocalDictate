"""Configuration management for LocalDictate."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
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


def get_config_dir() -> Path:
    """Return the platform-appropriate configuration directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "LocalDictate"


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


@dataclass
class AppConfig:
    hotkey_mode: str = "toggle"  # "toggle" | "push_to_talk"
    toggle_hotkey: str = "ctrl+alt+space"
    ptt_hotkey: str = "ctrl_r"
    model_size: str = "small"
    language: str = "auto"  # "auto" | "tr" | "en"
    compute_type: str = "int8"
    vad_filter: bool = True
    beam_size: int = 5
    cpu_threads: int = 0
    input_device: int | None = None
    restore_clipboard: bool = True
    paste_delay_ms: int = 50
    overlay_position: str = "bottom_center"  # "bottom_center" | "top_center"

    @property
    def active_hotkey(self) -> str:
        if self.hotkey_mode == "push_to_talk":
            return self.ptt_hotkey
        return self.toggle_hotkey

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        valid_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_names}
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
