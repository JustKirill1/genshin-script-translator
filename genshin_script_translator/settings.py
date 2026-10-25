"""User settings stored as JSON in the user data folder."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields

from . import paths


@dataclass
class AppSettings:
    language: str = "en"
    export_dir: str = ""                 # empty = paths.default_export_dir()
    use_dictionary: bool = True
    learn_on_correct: bool = True
    watch_clipboard: bool = False
    history_limit: int = 200
    author: str = ""                     # nickname written into exported libraries

    @staticmethod
    def load(path: str | None = None) -> "AppSettings":
        path = path or paths.settings_path()
        s = AppSettings()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return s
        names = {f.name for f in fields(AppSettings)}
        for k, v in data.items():
            if k in names:
                setattr(s, k, v)
        return s

    def save(self, path: str | None = None):
        path = path or paths.settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=1)

    def resolved_export_dir(self) -> str:
        return self.export_dir if self.export_dir and os.path.isdir(self.export_dir) else paths.default_export_dir()
