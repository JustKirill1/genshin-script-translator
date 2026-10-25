"""Tiny translation layer: UI strings live in ``i18n/<lang>.json``; English is the fallback.

To add a language, copy ``en.json`` to ``<code>.json``, translate the values and set
``"_language_name"`` to the language's own name — it appears in Settings automatically.
"""
from __future__ import annotations

import json
import os

from . import paths

_DIR = os.path.join(paths.package_dir(), "i18n")
_strings: dict[str, str] = {}
_fallback: dict[str, str] = {}
_lang = "en"


def _read(lang: str) -> dict[str, str]:
    try:
        with open(os.path.join(_DIR, f"{lang}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def available_languages() -> list[tuple[str, str]]:
    """[(code, native name)] sorted with English first."""
    out = []
    for name in sorted(os.listdir(_DIR)) if os.path.isdir(_DIR) else []:
        if name.endswith(".json"):
            code = name[:-5]
            out.append((code, _read(code).get("_language_name", code)))
    out.sort(key=lambda t: (t[0] != "en", t[1]))
    return out


def set_language(lang: str):
    global _strings, _fallback, _lang
    _fallback = _read("en")
    _strings = _read(lang) if lang != "en" else _fallback
    _lang = lang if _strings else "en"


def language() -> str:
    return _lang


def tr(key: str, **kwargs) -> str:
    if not _fallback:
        set_language(_lang)
    text = _strings.get(key) or _fallback.get(key) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text
