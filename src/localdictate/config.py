"""Configuration management for LocalDictate v1.0.0."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .hardware import get_os_data_dir
from .platform_utils import get_default_hotkeys

AVAILABLE_MODELS: list[tuple[str, str]] = [
    ("tiny", "Tiny (~75 MB — Ultra Fast)"),
    ("base", "Base (~145 MB — Fast)"),
    ("small", "Small (~465 MB — Recommended)"),
    ("medium", "Medium (~1.5 GB — High Accuracy)"),
    ("large-v3-turbo", "Large v3 Turbo (~1.6 GB — Flagship Accuracy)"),
]

AVAILABLE_LANGUAGES: list[tuple[str, str]] = [
    ("auto", "Auto-Detect (Multilingual)"),
    ("en", "English"),
    ("tr", "Türkçe (Turkish)"),
    ("de", "Deutsch (German)"),
    ("fr", "Français (French)"),
    ("es", "Español (Spanish)"),
    ("it", "Italiano (Italian)"),
    ("pt", "Português (Portuguese)"),
    ("ru", "Русский (Russian)"),
    ("ja", "日本語 (Japanese)"),
    ("ko", "한국어 (Korean)"),
    ("zh", "中文 (Chinese)"),
]

HOTKEY_MODES: list[tuple[str, str]] = [
    ("toggle", "Toggle (Press to Start / Stop)"),
    ("push_to_talk", "Push-to-Talk (Hold to Speak)"),
]

DICTATION_MODES: list[tuple[str, str]] = [
    ("cleanup", "Clean (Punctuation & Filler Cleanup)"),
    ("formal", "Formal (Business / Email Tone)"),
    ("concise", "Concise (Short & Direct)"),
    ("code", "Code (Preserve Tech / API Terms)"),
    ("bullet_notes", "Notes (Structured Bullet Points)"),
    ("git_commit", "Git Commit (Conventional Commit Msg)"),
    ("translate_en", "Voice-to-Translate (Any → English)"),
]

# Backwards-compatible alias used in v0.2.0
OLLAMA_STYLES = DICTATION_MODES

LLM_BACKENDS: list[tuple[str, str]] = [
    ("ollama", "Ollama Local (http://localhost:11434)"),
    ("openai_compat", "OpenAI-Compatible (LM Studio / llama.cpp)"),
]


def _default_toggle_hotkey() -> str:
    return get_default_hotkeys()[0]


def _default_ptt_hotkey() -> str:
    return get_default_hotkeys()[1]


def get_config_dir() -> Path:
    """Return the OS-native configuration & data directory."""
    return get_os_data_dir()


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


def get_history_db_path() -> Path:
    return get_config_dir() / "history.db"


def get_crash_log_path() -> Path:
    return get_config_dir() / "crash.log"


@dataclass
class AppConfig:
    # Interface & Experience
    ui_language: str = "en"  # "en" | "tr"
    minimize_to_tray: bool = True
    start_minimized: bool = False
    check_updates_on_startup: bool = True

    # Hotkeys (OS-aware defaults: Alt+Space / Right Option on macOS; Ctrl+Alt+Space / Right Ctrl on Win/Linux)
    hotkey_mode: str = "toggle"  # "toggle" | "push_to_talk"
    toggle_hotkey: str = field(default_factory=_default_toggle_hotkey)
    ptt_hotkey: str = field(default_factory=_default_ptt_hotkey)

    # Whisper STT Engine
    model_size: str = "small"
    language: str = "auto"
    compute_type: str = "int8"
    vad_filter: bool = True
    beam_size: int = 5
    cpu_threads: int = 0
    performance_profile: str = "auto"  # "auto" | "eco" | "balanced" | "performance"
    translate_to_english: bool = False

    # Audio & Recording Safeguards
    input_device: int | None = None
    sound_effects: bool = True
    max_recording_sec: int = 300
    silence_auto_stop_sec: float = 0.0  # 0 = manual stop; >0 = hands-free silence auto-stop

    # Injection & Overlay
    overlay_position: str = "bottom_center"  # "bottom_center" | "top_center"
    auto_paste: bool = True
    restore_clipboard: bool = True
    paste_delay_ms: int = 50
    clipboard_restore_delay_ms: int = 450
    direct_typing_fallback: bool = False
    append_trailing_space: bool = False

    # Productivity, Modes, History & Autostart
    dictation_mode: str = "cleanup"  # cleanup | formal | concise | code | bullet_notes | git_commit | translate_en
    app_aware_routing: bool = True
    app_mode_rules: dict[str, str] = field(default_factory=dict)
    voice_commands_enabled: bool = True
    save_history: bool = True
    launch_at_startup: bool = False

    # Personal Dictionary & Dynamic Snippets
    custom_vocabulary: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)
    snippets: dict[str, str] = field(default_factory=dict)

    # Optional Local / BYOK LLM Refinement
    ollama_enabled: bool = False
    llm_backend: str = "ollama"  # "ollama" | "openai_compat"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_style: str = "cleanup"
    ollama_timeout_sec: float = 8.0
    llm_api_key: str = ""
    offline_only: bool = True  # Air-Gapped Offline Lock (blocks non-localhost LLM URLs)
    custom_mode_prompts: dict[str, str] = field(default_factory=dict)

    @property
    def active_hotkey(self) -> str:
        if self.hotkey_mode == "push_to_talk":
            return self.ptt_hotkey
        return self.toggle_hotkey

    @property
    def effective_style(self) -> str:
        """Return the active dictation/refinement mode."""
        return self.dictation_mode or self.ollama_style or "cleanup"

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
        for list_field in ("custom_vocabulary",):
            if list_field in filtered and not isinstance(filtered[list_field], list):
                filtered[list_field] = []
        for dict_field in ("replacements", "snippets", "app_mode_rules", "custom_mode_prompts"):
            if dict_field in filtered and not isinstance(filtered[dict_field], dict):
                filtered[dict_field] = {}
        # Migrate v0.2.0 configs where ollama_style was set but dictation_mode was absent
        if "ollama_style" in filtered and "dictation_mode" not in filtered:
            filtered["dictation_mode"] = filtered["ollama_style"]
        return cls(**filtered)


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from disk, backing up corrupt JSON instead of silently wiping."""
    cfg_path = path or get_config_path()
    if not cfg_path.exists():
        return AppConfig()
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AppConfig()
        return AppConfig.from_dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        try:
            bak = cfg_path.with_name(f"{cfg_path.name}.corrupt.bak")
            cfg_path.replace(bak)
        except OSError:
            pass
        return AppConfig()
    except OSError:
        return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Atomically persist configuration to disk with restrictive POSIX permissions."""
    cfg_path = path or get_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(cfg_path.parent, 0o700)
        except OSError:
            pass
    payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
    tmp_path = cfg_path.with_name(f".{cfg_path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        if os.name == "posix":
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
        os.replace(tmp_path, cfg_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return cfg_path
