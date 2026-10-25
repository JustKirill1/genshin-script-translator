"""Library of learned glyph samples.

Three kinds of samples:

* ``builtin``  — shipped with the program (``data/library/builtin``), read-only. Deleting one only
  hides it for this user.
* ``user``     — learned on this computer (stored in the user data folder).
* ``imported`` — merged from a ``.gsrlib`` file shared by another player.

A ``.gsrlib`` file is a zip archive with ``manifest.json`` and one PNG mask per sample.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .alphabets import Template, imread_unicode
from .features import NOISE

BUILTIN, USER, IMPORTED = "builtin", "user", "imported"
FORMAT = "gsrlib"
FORMAT_VERSION = 1
_SAFE_NAMES = {",": "comma", ".": "period", "?": "unknown", "|": "bar", NOISE: "noise"}


def safe_char_name(char: str) -> str:
    return _SAFE_NAMES.get(char, char)


def encode_mask(mask: np.ndarray) -> bytes:
    m = ((mask > 127) * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", m)
    if not ok:
        raise ValueError("cannot encode mask")
    return buf.tobytes()


def decode_mask(data: bytes) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return ((img > 127) * 255).astype(np.uint8)


def sample_id(alphabet: str, png: bytes) -> str:
    return hashlib.sha1(alphabet.encode() + b"\0" + png).hexdigest()[:16]


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


@dataclass
class Sample:
    id: str
    alphabet: str
    char: str
    file: str               # path relative to the library folder it lives in
    rel_height: float = 1.0
    source: str = USER
    author: str = ""
    created: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("source")         # implied by the folder
        return d


class Library:
    def __init__(self, builtin_dir: str, user_dir: str):
        self.builtin_dir = builtin_dir
        self.user_dir = user_dir
        self._builtin: list[Sample] = []
        self._user: list[Sample] = []
        self.hidden_builtin: set[str] = set()
        self._mask_cache: dict[str, np.ndarray] = {}
        self.reload()

    # ------------------------------------------------------------------ storage
    @staticmethod
    def _read_index(folder: str) -> dict:
        path = os.path.join(folder, "index.json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def reload(self):
        b = self._read_index(self.builtin_dir)
        self._builtin = [Sample(**{**s, "source": BUILTIN}) for s in b.get("samples", [])]
        u = self._read_index(self.user_dir)
        self._user = []
        for s in u.get("samples", []):
            src = s.pop("source", None) or (IMPORTED if s.get("author") else USER)
            self._user.append(Sample(**{**s, "source": src}))
        self.hidden_builtin = set(u.get("hidden_builtin", []))

    def _save_user(self):
        os.makedirs(self.user_dir, exist_ok=True)
        data = {
            "format": FORMAT, "version": FORMAT_VERSION,
            "samples": [{**s.to_json(), "source": s.source} for s in self._user],
            "hidden_builtin": sorted(self.hidden_builtin),
        }
        tmp = os.path.join(self.user_dir, "index.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(self.user_dir, "index.json"))

    def path_of(self, s: Sample) -> str:
        base = self.builtin_dir if s.source == BUILTIN else self.user_dir
        return os.path.join(base, s.file)

    def load_mask(self, s: Sample) -> np.ndarray | None:
        m = self._mask_cache.get(s.id)
        if m is None:
            img = imread_unicode(self.path_of(s))
            if img is None:
                return None
            m = ((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) > 127) * 255).astype(np.uint8)
            if m.max() == 0:
                return None
            self._mask_cache[s.id] = m
        return m

    # ------------------------------------------------------------------ queries
    def samples(self, alphabet: str | None = None, include_hidden: bool = False) -> list[Sample]:
        out = [s for s in self._builtin if include_hidden or s.id not in self.hidden_builtin]
        out += self._user
        return [s for s in out if alphabet is None or s.alphabet == alphabet]

    def get(self, sid: str) -> Sample | None:
        return next((s for s in self._builtin + self._user if s.id == sid), None)

    def count(self, alphabet: str | None = None, source: str | None = None) -> int:
        return sum(1 for s in self.samples(alphabet) if source is None or s.source == source)

    def templates_for(self, alphabet: str) -> list[Template]:
        out = []
        for s in self.samples(alphabet):
            m = self.load_mask(s)
            if m is not None:
                out.append(Template(s.char, m, float(s.rel_height)))
        return out

    # ------------------------------------------------------------------ changes
    def add(self, alphabet: str, char: str, mask: np.ndarray, rel_height: float,
            source: str = USER, author: str = "", created: str = "") -> Sample | None:
        """Store a sample. Returns None if the very same glyph image is already in the library."""
        png = encode_mask(mask)
        sid = sample_id(alphabet, png)
        if self.get(sid) is not None:
            return None
        sub = os.path.join(self.user_dir, alphabet)
        os.makedirs(sub, exist_ok=True)
        rel_file = f"{alphabet}/{safe_char_name(char)}_{sid}.png"
        with open(os.path.join(self.user_dir, rel_file), "wb") as f:
            f.write(png)
        s = Sample(sid, alphabet, char, rel_file, round(float(rel_height), 3), source, author, created or _now())
        self._user.append(s)
        self._save_user()
        return s

    def remove(self, sid: str) -> bool:
        s = self.get(sid)
        if s is None:
            return False
        if s.source == BUILTIN:
            self.hidden_builtin.add(sid)
        else:
            self._user = [u for u in self._user if u.id != sid]
            try:
                os.remove(self.path_of(s))
            except OSError:
                pass
        self._mask_cache.pop(sid, None)
        self._save_user()
        return True

    def relabel(self, sid: str, char: str) -> Sample | None:
        s = self.get(sid)
        if s is None or s.char == char:
            return s
        if s.source == BUILTIN:
            # built-in files are read-only: copy into the user library and hide the original
            m = self.load_mask(s)
            self.hidden_builtin.add(sid)
            self._save_user()
            return self.add(s.alphabet, char, m, s.rel_height, USER, s.author) if m is not None else None
        old = self.path_of(s)
        s.char = char
        s.file = f"{s.alphabet}/{safe_char_name(char)}_{s.id}.png"
        try:
            os.replace(old, self.path_of(s))
        except OSError:
            pass
        self._save_user()
        return s

    def restore_builtin(self) -> int:
        n = len(self.hidden_builtin)
        self.hidden_builtin.clear()
        self._save_user()
        return n

    def clear_user(self, alphabet: str | None = None) -> int:
        doomed = [s for s in self._user if alphabet is None or s.alphabet == alphabet]
        for s in doomed:
            try:
                os.remove(self.path_of(s))
            except OSError:
                pass
            self._mask_cache.pop(s.id, None)
        self._user = [s for s in self._user if s not in doomed]
        self._save_user()
        return len(doomed)

    # ------------------------------------------------------------------ sharing
    def export(self, path: str, alphabets: list[str] | None = None, include_builtin: bool = False,
               include_noise: bool = True, author: str = "", app_version: str = "") -> int:
        chosen = [s for s in self.samples()
                  if (alphabets is None or s.alphabet in alphabets)
                  and (include_builtin or s.source != BUILTIN)
                  and (include_noise or s.char != NOISE)]
        manifest = {"format": FORMAT, "version": FORMAT_VERSION, "author": author,
                    "created": _now(), "app_version": app_version, "samples": []}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for s in chosen:
                try:
                    with open(self.path_of(s), "rb") as f:
                        png = f.read()
                except OSError:
                    continue
                name = f"samples/{s.alphabet}/{safe_char_name(s.char)}_{s.id}.png"
                z.writestr(name, png)
                manifest["samples"].append({"alphabet": s.alphabet, "char": s.char, "file": name,
                                            "rel_height": s.rel_height,
                                            "author": s.author or (author if s.source == USER else ""),
                                            "created": s.created})
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        return len(manifest["samples"])

    @staticmethod
    def read_manifest(path: str) -> dict:
        """Summary of a .gsrlib file (or a legacy ``index.json`` from version 0.0) for the import dialog."""
        if path.lower().endswith(".json"):
            items = Library._legacy_items(path)
            author, created = "", ""
        else:
            with zipfile.ZipFile(path) as z:
                m = json.loads(z.read("manifest.json").decode("utf-8"))
            if m.get("format") != FORMAT:
                raise ValueError("not a .gsrlib file")
            items, author, created = m.get("samples", []), m.get("author", ""), m.get("created", "")
        per_alphabet: dict[str, int] = {}
        noise = 0
        for it in items:
            per_alphabet[it["alphabet"]] = per_alphabet.get(it["alphabet"], 0) + 1
            noise += it["char"] == NOISE
        return {"author": author, "created": created, "total": len(items),
                "per_alphabet": per_alphabet, "noise": noise}

    @staticmethod
    def _legacy_items(index_path: str) -> list[dict]:
        with open(index_path, encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, dict):
            items = items.get("samples", [])
        return items

    def import_package(self, path: str, include_noise: bool = True, alphabets: list[str] | None = None,
                       default_author: str = "") -> tuple[int, int]:
        """Merge samples from a .gsrlib (or legacy index.json). Returns (added, skipped as duplicates)."""
        added = skipped = 0

        def take(alphabet, char, png, rel, author, created, source):
            nonlocal added, skipped
            if alphabets is not None and alphabet not in alphabets:
                return
            if char == NOISE and not include_noise:
                return
            m = decode_mask(png)
            if m is None:
                return
            if self.add(alphabet, char, m, rel, source, author, created) is None:
                skipped += 1
            else:
                added += 1

        if path.lower().endswith(".json"):
            base = os.path.dirname(path)
            for it in self._legacy_items(path):
                try:
                    with open(os.path.join(base, it["file"]), "rb") as f:
                        png = f.read()
                except OSError:
                    continue
                take(it["alphabet"], it["char"], png, float(it.get("rel_height", 1.0)),
                     it.get("author", default_author), it.get("created", ""), USER)
            return added, skipped

        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read("manifest.json").decode("utf-8"))
            if m.get("format") != FORMAT:
                raise ValueError("not a .gsrlib file")
            pack_author = m.get("author", "") or default_author
            for it in m.get("samples", []):
                try:
                    png = z.read(it["file"])
                except KeyError:
                    continue
                take(it["alphabet"], it["char"], png, float(it.get("rel_height", 1.0)),
                     it.get("author") or pack_author, it.get("created", ""), IMPORTED)
        return added, skipped

    def save_builtin_from(self, samples: list[tuple[str, str, np.ndarray, float]]):
        """Developer helper: (re)create the built-in library folder from (alphabet, char, mask, rel)."""
        if os.path.isdir(self.builtin_dir):
            shutil.rmtree(self.builtin_dir)
        os.makedirs(self.builtin_dir)
        items = []
        for alphabet, char, mask, rel in samples:
            png = encode_mask(mask)
            sid = sample_id(alphabet, png)
            rel_file = f"{alphabet}/{safe_char_name(char)}_{sid}.png"
            os.makedirs(os.path.join(self.builtin_dir, alphabet), exist_ok=True)
            with open(os.path.join(self.builtin_dir, rel_file), "wb") as f:
                f.write(png)
            items.append(Sample(sid, alphabet, char, rel_file, round(float(rel), 3), BUILTIN).to_json())
        with open(os.path.join(self.builtin_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"format": FORMAT, "version": FORMAT_VERSION, "samples": items}, f, indent=1)
        self.reload()


def mask_thumbnail(mask: np.ndarray, size: int = 56) -> np.ndarray:
    """White glyph on dark square — used by the library window and the accept dialog."""
    h, w = mask.shape
    s = (size - 6) / max(h, w)
    m = cv2.resize(mask, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    out = np.full((size, size), 30, np.uint8)
    y, x = (size - m.shape[0]) // 2, (size - m.shape[1]) // 2
    out[y:y + m.shape[0], x:x + m.shape[1]] = np.maximum(30, m)
    return out

