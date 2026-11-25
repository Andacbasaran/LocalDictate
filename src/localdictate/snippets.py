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
    if not clean:
        raise ValueError("Term cannot be empty or whitespace.")
    escaped = re.escape(clean)
    left = r"(?<!\w)" if (clean[0].isalnum() or clean[0] == "_") else r"(?<!\S)"
    right = (
        r"(?!\w)"
        if (clean[-1].isalnum() or clean[-1] == "_")
        else r"(?=$|[\s,.;:!?()\[\]{}\"'/\\])"
    )
    return re.compile(f"{left}{escaped}{right}", re.IGNORECASE)


# Ambiguous single-word nouns that should only trigger at end-of-clause/sentence or before another command
_AMBIGUOUS_VOICE_WORDS = frozenset({"period", "colon", "nokta"})


def _compile_voice_commands() -> list[tuple[re.Pattern[str], str, bool]]:
    compiled: list[tuple[re.Pattern[str], str, bool]] = []
    for phrase, replacement in VOICE_COMMANDS:
        base_pat = build_safe_term_pattern(phrase).pattern
        is_break = replacement in ("\n", "\n\n")
        if is_break:
            pat = re.compile(rf"[ \t]*{base_pat}[ \t]*", re.IGNORECASE)
        elif phrase.lower() in _AMBIGUOUS_VOICE_WORDS:
            # Only trigger ambiguous words like 'period'/'colon'/'nokta' at end of utterance/line
            # or followed by punctuation/line-break command (never mid-phrase like "during this period of time")
            pat = re.compile(rf"[ \t]*{base_pat}(?=$|[\n,.;:!?])", re.IGNORECASE)
        else:
            pat = re.compile(rf"[ \t]*{base_pat}", re.IGNORECASE)
        compiled.append((pat, replacement, is_break))
    return compiled


_COMPILED_VOICE_COMMANDS = _compile_voice_commands()


def apply_voice_commands(text: str) -> str:
    """Convert spoken EN/TR formatting commands (e.g. 'new line', 'yeni paragraf', 'comma') into symbols."""
    if not text:
        return text

    result = text
    any_replaced = False
    for pat, replacement, is_break in _COMPILED_VOICE_COMMANDS:
        if is_break:
            new_res, count = pat.subn(lambda _m, r=replacement: r, result)
        else:
            # Avoid duplicating an identical punctuation mark immediately before or after the command
            def _sub_punct(m: re.Match[str], r: str = replacement) -> str:
                return r

            new_res, count = pat.subn(_sub_punct, result)
            if count > 0 and replacement in (",", ".", ";", ":", "!", "?"):
                esc = re.escape(replacement)
                # Collapse accidental double punctuation produced right at the substituted symbol
                # without touching intentional `...` ellipses, `::`, or `../` paths!
                if replacement == ".":
                    new_res = re.sub(r"(?<!\.)\.\.(?![./])", ".", new_res)
                elif replacement == ":":
                    new_res = re.sub(r"(?<!\w)::(?!\w)", ":", new_res)
                else:
                    new_res = re.sub(rf"{esc}{{2,}}", replacement, new_res)
        if count > 0:
            any_replaced = True
            result = new_res

    if not any_replaced:
        return result

    # Clean horizontal spaces without destroying newlines
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in result.split("\n")]
    result = "\n".join(lines)
    # Remove spaces before punctuation only when NOT followed by word/path chars (keeps `.env`, `../src`)
    result = re.sub(r"[ \t]+([,.;:!?])(?=$|\s)", r"\1", result)
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
    """Apply safe dictionary replacements & dynamic snippets (longest match first, lazy template expansion)."""
    if not text or not replacements:
        return text

    # Build a single longest-first alternating pattern so replacements don't chain-corrupt each other
    # and dynamic templates ({{clipboard}}) are ONLY expanded when a trigger actually matches!
    ordered: list[tuple[str, str]] = []
    seen_lower: set[str] = set()
    for src, dst in sorted(replacements.items(), key=lambda kv: len(kv[0]), reverse=True):
        src_clean = src.strip()
        if not src_clean:
            continue
        low = src_clean.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        ordered.append((src_clean, str(dst)))

    if not ordered:
        return text

    parts = [f"(?P<r{idx}>{build_safe_term_pattern(src).pattern})" for idx, (src, _) in enumerate(ordered)]
    combined = re.compile("|".join(parts), re.IGNORECASE)
    dst_by_group = {f"r{idx}": dst for idx, (_, dst) in enumerate(ordered)}
    expanded_cache: Dict[str, str] = {}

    def _replace(match: re.Match[str]) -> str:
        gname = match.lastgroup
        if not gname:
            return match.group(0)
        if gname not in expanded_cache:
            expanded_cache[gname] = expand_snippet_templates(
                dst_by_group[gname],
                clipboard_getter=clipboard_getter,
                now=now,
            )
        return expanded_cache[gname]

    return combined.sub(_replace, text)


def merge_starter_pack(existing: Dict[str, str], pack_id: str) -> Dict[str, str]:
    """Merge a named starter pack into an existing snippets dictionary without overwriting user rules."""
    pack = STARTER_PACKS.get(pack_id, {})
    merged = dict(existing)
    for k, v in pack.items():
        if k not in merged:
            merged[k] = v
    return merged
