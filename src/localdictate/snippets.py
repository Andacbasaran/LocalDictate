"""Smart voice formatting commands, safe dictionary replacements, and dynamic snippet templates."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, Dict, Optional

import pyperclip

# Starter snippet packs users can install with one click in Studio
STARTER_PACKS: Dict[str, Dict[str, str]] = {
    "developer": {
        "lgtm": "Looks good to me — clean implementation, ready to merge.",
        "pr checklist": (
            "## Verification\n"
            "- [ ] Unit tests pass\n"
            "- [ ] Linter clean\n"
            "- [ ] Tested on target OS"
        ),
        "todo note": "TODO({{iso_date}}): ",
        "daily standup": "Standup ({{date}}):\n- Yesterday: \n- Today: \n- Blockers: None",
        "code review": "Thanks for the PR! Left a couple of small suggestions inline.",
    },
    "business_en": {
        "my signoff": "Best regards,\n",
        "today date": "{{date}}",
        "iso date": "{{iso_date}}",
        "meeting follow up": (
            "Thanks everyone for joining today's session ({{date}}). "
            "Here are the key action items and next steps:"
        ),
        "paste link": "Here is the link we discussed: {{clipboard}}",
    },
    "business_tr": {
        "imzam": "Saygılarımla,\n",
        "bugünün tarihi": "{{date}}",
        "toplantı özeti": (
            "Bugünkü toplantıya katılımınız için teşekkürler ({{date}}). "
            "Öne çıkan aksiyon maddeleri aşağıdadır:"
        ),
        "geri dönüş": "Bilgilendirme için teşekkür ederim, en kısa sürede dönüş yapacağım.",
        "pano yapıştır": "İlgili bağlantı: {{clipboard}}",
    },
}

# Spoken formatting commands (ordered longest-first to avoid partial matches)
VOICE_COMMANDS: list[tuple[str, str]] = [
    ("new paragraph", "\n\n"),
    ("yeni paragraf", "\n\n"),
    ("new line", "\n"),
    ("yeni satır", "\n"),
    ("yeni satir", "\n"),
    ("question mark", "?"),
    ("soru işareti", "?"),
    ("soru isareti", "?"),
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("ünlem işareti", "!"),
    ("ünlem", "!"),
    ("full stop", "."),
    ("semicolon", ";"),
    ("noktalı virgül", ";"),
    ("iki nokta", ":"),
    ("period", "."),
    ("nokta", "."),
    ("comma", ","),
    ("virgül", ","),
    ("colon", ":"),
]


def _default_clipboard_getter() -> str:
    try:
        return str(pyperclip.paste() or "")
    except Exception:
        return ""


def build_safe_term_pattern(term: str) -> re.Pattern[str]:
    """Build a case-insensitive boundary-aware regex safe for symbols like C++, node.js, .env, C#."""
    clean = term.strip()
    escaped = re.escape(clean)
    left = r"(?<!\w)" if (clean[0].isalnum() or clean[0] == "_") else r"(?<!\S)"
    right = (
        r"(?!\w)"
        if (clean[-1].isalnum() or clean[-1] == "_")
        else r"(?=$|[\s,.;:!?()\[\]{}\"'/\\])"
    )
    return re.compile(f"{left}{escaped}{right}", re.IGNORECASE)


def apply_voice_commands(text: str) -> str:
    """Convert spoken EN/TR formatting commands (e.g. 'new line', 'yeni paragraf', 'comma') into symbols."""
    if not text:
        return text

    result = text
    for phrase, replacement in VOICE_COMMANDS:
        pattern = build_safe_term_pattern(phrase)
        if replacement in ("\n", "\n\n"):
            # Consume surrounding spaces around line breaks cleanly
            break_pat = re.compile(rf"[ \t]*{pattern.pattern}[ \t]*", re.IGNORECASE)
            result = break_pat.sub(lambda _m, r=replacement: r, result)
        else:
            # Attach punctuation cleanly to preceding word
            punct_pat = re.compile(rf"[ \t]*{pattern.pattern}", re.IGNORECASE)
            result = punct_pat.sub(lambda _m, r=replacement: r, result)

    # Collapse accidental double punctuation like ".." produced if Whisper already added a period
    result = re.sub(r"([,.;:!?])\1+", r"\1", result)
    # Clean horizontal spaces without destroying newlines
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in result.split("\n")]
    result = "\n".join(lines)
    # Remove leading spaces before punctuation on each line
    result = re.sub(r"[ \t]+([,.;:!?])", r"\1", result)
    return result.strip()


def expand_snippet_templates(
    text: str,
    clipboard_getter: Optional[Callable[[], str]] = None,
    now: Optional[datetime] = None,
) -> str:
    """Expand dynamic template variables: {{date}}, {{iso_date}}, {{time}}, {{datetime}}, {{clipboard}}."""
    if not text or "{{" not in text:
        return text

    dt = now or datetime.now()
    values: Dict[str, str] = {
        "date": dt.strftime("%Y-%m-%d"),
        "iso_date": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H:%M"),
        "datetime": dt.strftime("%Y-%m-%d %H:%M"),
        "year": dt.strftime("%Y"),
    }

    def _replace_var(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        if key == "clipboard":
            getter = clipboard_getter or _default_clipboard_getter
            try:
                return str(getter() or "")
            except Exception:
                return ""
        return values.get(key, match.group(0))

    return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", _replace_var, text)


def apply_replacements(
    text: str,
    replacements: Dict[str, str],
    clipboard_getter: Optional[Callable[[], str]] = None,
    now: Optional[datetime] = None,
) -> str:
    """Apply safe dictionary replacements & dynamic snippets (longest match first, backslash-safe)."""
    if not text or not replacements:
        return text

    result = text
    for src, dst in sorted(replacements.items(), key=lambda kv: len(kv[0]), reverse=True):
        src_clean = src.strip()
        if not src_clean:
            continue
        expanded_dst = expand_snippet_templates(
            str(dst),
            clipboard_getter=clipboard_getter,
            now=now,
        )
        pattern = build_safe_term_pattern(src_clean)
        # Use lambda replacement so backslashes (e.g. C:\Users\name) never trigger re.sub group escapes
        result = pattern.sub(lambda _m, d=expanded_dst: d, result)
    return result


def merge_starter_pack(existing: Dict[str, str], pack_id: str) -> Dict[str, str]:
    """Merge a named starter pack into an existing snippets dictionary without overwriting user rules."""
    pack = STARTER_PACKS.get(pack_id, {})
    merged = dict(existing)
    for k, v in pack.items():
        if k not in merged:
            merged[k] = v
    return merged
