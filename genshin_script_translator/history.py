"""Recognition history kept between sessions: text, a thumbnail, the image and the selection."""
from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .alphabets import imread_unicode, imwrite_unicode
from .selection import Selection

MAX_SIDE = 2560          # larger images are downscaled before saving
THUMB = 96


@dataclass
class HistoryEntry:
    id: str
    time: str
    alphabet: str
    text: str
    raw: str
    image: str               # file names inside the history folder
    thumb: str
    selection: list = field(default_factory=list)    # Selection.to_json() in stored-image coordinates


class History:
    def __init__(self, folder: str, limit: int = 200):
        self.folder = folder
        self.limit = limit
        self.entries: list[HistoryEntry] = []
        self._load()

    def _index(self) -> str:
        return os.path.join(self.folder, "index.json")

    def _load(self):
        try:
            with open(self._index(), encoding="utf-8") as f:
                self.entries = [HistoryEntry(**e) for e in json.load(f)]
        except (OSError, ValueError, TypeError):
            self.entries = []

    def _save(self):
        os.makedirs(self.folder, exist_ok=True)
        tmp = self._index() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.entries], f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._index())

    def add(self, img: np.ndarray, text: str, raw: str, alphabet: str,
            selection: Selection | None, focus_box: tuple[int, int, int, int] | None = None) -> HistoryEntry:
        os.makedirs(self.folder, exist_ok=True)
        eid = uuid.uuid4().hex[:12]
        h, w = img.shape[:2]
        f = min(1.0, MAX_SIDE / max(h, w))
        stored = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
        sel = selection.scaled(f) if selection is not None else Selection()
        imwrite_unicode(os.path.join(self.folder, f"{eid}.jpg"), stored)
        if focus_box:
            x0, y0, x1, y1 = focus_box
            crop = img[y0:y1, x0:x1]
        else:
            crop = img
        k = THUMB / max(crop.shape[:2])
        thumb = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else crop
        imwrite_unicode(os.path.join(self.folder, f"{eid}_t.png"), thumb)
        e = HistoryEntry(eid, _dt.datetime.now().replace(microsecond=0).isoformat(), alphabet, text, raw,
                         f"{eid}.jpg", f"{eid}_t.png", sel.to_json())
        self.entries.insert(0, e)
        self._trim()
        self._save()
        return e

    def _trim(self):
        while len(self.entries) > max(1, self.limit):
            self._delete_files(self.entries.pop())

    def _delete_files(self, e: HistoryEntry):
        for name in (e.image, e.thumb):
            try:
                os.remove(os.path.join(self.folder, name))
            except OSError:
                pass

    def set_limit(self, limit: int):
        self.limit = limit
        self._trim()
        self._save()

    def remove(self, eid: str):
        for e in [e for e in self.entries if e.id == eid]:
            self._delete_files(e)
        self.entries = [e for e in self.entries if e.id != eid]
        self._save()

    def clear(self):
        for e in self.entries:
            self._delete_files(e)
        self.entries = []
        self._save()

    def image(self, e: HistoryEntry) -> np.ndarray | None:
        return imread_unicode(os.path.join(self.folder, e.image))

    def thumb_path(self, e: HistoryEntry) -> str:
        return os.path.join(self.folder, e.thumb)

    def selection(self, e: HistoryEntry) -> Selection:
        return Selection.from_json(e.selection)
