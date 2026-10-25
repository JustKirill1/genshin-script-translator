"""Loading the alphabet charts and cutting them into glyph templates.

All charts except Nod-Krai share one layout: a 5-column grid, each cell holding a golden glyph
on top and its Latin label below. The Nod-Krai chart is black glyphs on white with red labels,
so it is cut by the label positions instead.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import cv2
import numpy as np

LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Grid borders of the 1000 px wide charts (identical for every "golden" chart).
GRID_X = [41, 225, 408, 592, 775, 958]
GRID_Y = [89, 301, 513, 725, 937, 1150, 1357]


@dataclass
class AlphabetSpec:
    key: str
    title: str                      # English name; translated names live in i18n files
    file: str
    kind: str                       # "grid" | "nodkrai"
    labels: list                    # cell labels in reading order; None = skip the cell
    notes: str = ""                 # English note; i18n key is "alphabet_note.<key>"
    english: bool = True            # text is English, so the English dictionary applies


SPECS: list[AlphabetSpec] = [
    AlphabetSpec(
        "common", "Teyvat Common (Mondstadt, Liyue)",
        "Teyvat_Common_Language_Alphabet.webp", "grid",
        LETTERS + [None],  # 27th cell is the line-continuation mark, same shape as "A"
    ),
    AlphabetSpec(
        "inazuma", "Inazuma", "Inazuma_letters.webp", "grid",
        LETTERS + ["S", "I"],
        "Inazuman text is romanized Japanese, usually written with only the first letter of each "
        "syllable (ka, ki, ku → K), so the result is a letter skeleton, not English.",
        english=False,
    ),
    AlphabetSpec("sumeru", "Sumeru", "Sumeru_Alphabet.webp", "grid", LETTERS),
    AlphabetSpec("deshret", "Desert (Deshret)", "Deshret_Alphabet.webp", "grid", LETTERS),
    AlphabetSpec("fontaine", "Fontaine", "Fontaine_Script.webp", "grid", LETTERS),
    AlphabetSpec(
        "ancient", "Ancient Teyvat script", "Ancient_Teyvat_Script_Alphabet.webp",
        "grid", LETTERS + [",", ".", "?", "?"],
        "Two signs of the chart are undeciphered and are shown as \"?\".",
    ),
    AlphabetSpec(
        "nodkrai", "Nod-Krai", "Nod-Krai_Script.webp", "nodkrai", LETTERS,
        "The chart has no signs for J, Q and X.",
    ),
]


@dataclass
class Template:
    char: str
    mask: np.ndarray            # uint8 0/255, cropped to the glyph
    rel_height: float = 1.0     # height relative to the typical glyph height of the alphabet


@dataclass
class Alphabet:
    spec: AlphabetSpec
    sheet: np.ndarray                       # BGR image of the chart
    templates: list[Template] = field(default_factory=list)

    @property
    def key(self):
        return self.spec.key

    @property
    def title(self):
        return self.spec.title

    @property
    def chars(self) -> list[str]:
        return sorted({t.char for t in self.templates})


def imread_unicode(path: str) -> np.ndarray | None:
    """cv2.imread cannot open non-ASCII paths on Windows, so decode through numpy. Returns BGR."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        img = (img[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return img


def imwrite_unicode(path: str, img: np.ndarray) -> bool:
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    buf.tofile(path)
    return True


def _crop_to_content(mask: np.ndarray, min_area: int = 6) -> np.ndarray | None:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[lab == i] = 255
    ys, xs = np.nonzero(keep)
    if len(xs) == 0:
        return None
    return keep[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _gold_mask(cell: np.ndarray) -> np.ndarray:
    c = cell.astype(np.int16)
    b, g, r = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    m = (r > 105) & (r - b > 30) & (g > b)
    return (m * 255).astype(np.uint8)


def _extract_grid(sheet: np.ndarray, labels: list) -> list[Template]:
    out = []
    for idx, label in enumerate(labels):
        if label is None:
            continue
        r, c = divmod(idx, 5)
        x0, x1 = GRID_X[c] + 4, GRID_X[c + 1] - 4
        y0 = GRID_Y[r] + 6
        y1 = GRID_Y[r] + 148           # the cell label starts below this line
        mask = _crop_to_content(_gold_mask(sheet[y0:y1, x0:x1]), min_area=12)
        if mask is not None:
            out.append(Template(label, mask))
    return out


def _extract_nodkrai(sheet: np.ndarray, labels: list) -> list[Template]:
    c = sheet.astype(np.int16)
    b, g, r = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    red = ((r > 150) & (g < 120) & (b < 120)).astype(np.uint8) * 255
    gray = cv2.cvtColor(sheet, cv2.COLOR_BGR2GRAY)
    dark = ((gray < 150) & (red == 0)).astype(np.uint8) * 255

    # Labels: red components, sorted row by row.
    n, _, stats, _ = cv2.connectedComponentsWithStats(red, connectivity=8)
    boxes = [(stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]) for i in range(1, n)
             if stats[i, cv2.CC_STAT_AREA] > 8]
    boxes.sort(key=lambda bb: (bb[1] // 20, bb[0]))
    # Labels for J/Q/X exist but have no glyph above them — those cells come out empty.
    out = []
    for (x, y, w, h), label in zip(boxes, labels):
        cx = x + w / 2
        x0, x1 = int(cx - 24), int(cx + 24)
        y0, y1 = max(0, y - 40), y - 2
        mask = _crop_to_content(dark[y0:y1, max(0, x0):x1], min_area=3)
        if mask is None or mask.shape[0] < 8:
            continue
        # The chart is low-resolution: upscale to ~80 px height like the other charts.
        scale = 80.0 / mask.shape[0]
        big = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        big = cv2.GaussianBlur(big, (5, 5), 0)
        out.append(Template(label, ((big > 127) * 255).astype(np.uint8)))
    return out


def load_alphabets(directory: str) -> list[Alphabet]:
    result = []
    for spec in SPECS:
        sheet = imread_unicode(os.path.join(directory, spec.file))
        if sheet is None:
            continue
        tpls = _extract_grid(sheet, spec.labels) if spec.kind == "grid" else _extract_nodkrai(sheet, spec.labels)
        if not tpls:
            continue
        med = float(np.median([t.mask.shape[0] for t in tpls]))
        for t in tpls:
            t.rel_height = t.mask.shape[0] / med
        result.append(Alphabet(spec, sheet, tpls))
    return result
