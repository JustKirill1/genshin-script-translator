"""Where things live: bundled resources (read-only) and per-user data (writable).

* Resources (alphabet charts, word lists, built-in glyph library, translations) sit next to the
  source code, or inside the PyInstaller bundle when running as a frozen .exe.
* User data (learned glyphs, settings, history) goes to ``%APPDATA%\\GenshinScriptTranslator`` on
  Windows (``~/.local/share/GenshinScriptTranslator`` elsewhere). If a file named ``portable.txt``
  sits next to the program, user data is kept in a ``userdata`` folder beside it instead.
"""
from __future__ import annotations

import os
import sys

from . import APP_ID


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Folder the user launched the program from (repository root or the folder with the .exe)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir() -> str:
    """Folder that contains ``alphabets/`` and ``data/``."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", app_dir())
    return app_dir()


def package_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def alphabets_dir() -> str:
    return os.path.join(resource_dir(), "alphabets")


def data_dir() -> str:
    return os.path.join(resource_dir(), "data")


def builtin_library_dir() -> str:
    return os.path.join(data_dir(), "library", "builtin")


def is_portable() -> bool:
    return os.path.isfile(os.path.join(app_dir(), "portable.txt"))


def user_data_dir(create: bool = True) -> str:
    override = os.environ.get("GST_USER_DATA")          # used by tests
    if override:
        path = override
    elif is_portable():
        path = os.path.join(app_dir(), "userdata")
    elif sys.platform.startswith("win"):
        path = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_ID)
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        path = os.path.join(base, APP_ID)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def user_library_dir() -> str:
    return os.path.join(user_data_dir(), "library")


def history_dir() -> str:
    return os.path.join(user_data_dir(), "history")


def settings_path() -> str:
    return os.path.join(user_data_dir(), "settings.json")


def user_words_path() -> str:
    return os.path.join(user_data_dir(), "user_words.txt")


def log_path() -> str:
    return os.path.join(user_data_dir(), "error.log")


def default_export_dir() -> str:
    """``docs/images`` of the repository when running from source, otherwise the Pictures folder."""
    repo_images = os.path.join(app_dir(), "docs", "images")
    if os.path.isdir(repo_images):
        return repo_images
    pictures = os.path.join(os.path.expanduser("~"), "Pictures")
    return pictures if os.path.isdir(pictures) else os.path.expanduser("~")
