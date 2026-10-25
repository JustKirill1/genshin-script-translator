"""Text recognition on a screenshot: binarization → lines → glyphs → letters → words.

Pipeline overview
-----------------
1. **Binarize** the selected area several ways (global Otsu, background flattening, adaptive
   threshold) in both polarities (light text on dark / dark on light).
2. Find connected **components**, estimate the glyph size, cut touching glyphs at narrow points.
3. Group components into **lines** (horizontal, or vertical columns for Inazuma).
4. Inside each line, a dynamic program decides which neighbouring components form one glyph
   (letters made of several strokes and dots), scoring each candidate with the classifier.
5. Try every alphabet and the rotations/mirrors; rank readings by glyph similarity, dictionary
   hits and a few sanity priors; correct the best one with the dictionary.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

import cv2
import numpy as np

from . import paths
from .alphabets import Alphabet, load_alphabets
from .features import NOISE, Classifier, features
from .library import Library
from .lexicon import Lexicon

TRANSFORMS = ("none", "rot180", "flip_h", "flip_v")
BINARIZATIONS = ("otsu", "flat", "adaptive")
ORIENTATIONS = ("h", "v_rtl", "v_ltr")


@dataclass
class Settings:
    alphabet: str = "auto"          # alphabet key or "auto"
    orientation: str = "auto"       # "auto" | "h" | "v_rtl" | "v_ltr"
    binarize: str = "auto"          # "auto" | "otsu" | "flat" | "adaptive" | "color"
    transform: str = "auto"         # "auto" | "none" | "rot180" | "flip_h" | "flip_v"
    polarity: str = "auto"          # "auto" | "light" | "dark"
    color: tuple | None = None      # BGR for the "color" mode
    color_tol: int = 45
    space_factor: float = 0.0       # 0 = automatic, otherwise a fraction of the glyph size
    use_dictionary: bool = True
    max_group: int = 6              # how many components may form one glyph


@dataclass
class Glyph:
    x: int
    y: int
    w: int
    h: int
    scores: np.ndarray              # similarity to every letter of the alphabet
    char: str
    manual: bool = False            # set by the user (corrected or confirmed)

    def candidates(self, chars: list[str], k: int = 6) -> list[tuple[str, float]]:
        idx = np.argsort(-self.scores)[:k]
        return [(chars[i], float(self.scores[i])) for i in idx]

    @property
    def confidence(self) -> float:
        return float(self.scores.max())


@dataclass
class Result:
    alphabet: Alphabet
    chars: list[str]
    orientation: str
    transform: str
    glyphs: list[Glyph]
    lines: list[list[list[int]]]    # line → word → glyph indices
    quality: float
    mask: np.ndarray | None
    offset: tuple[int, int] = (0, 0)
    size_ref: float = 0.0           # typical glyph height in pixels of the source image
    work_mask: np.ndarray | None = None   # mask at working (possibly upscaled) resolution
    scale: float = 1.0
    corrected: list[list[tuple[str, bool]]] = field(default_factory=list)   # line → [(word, corrected?)]
    alternatives: list[tuple[str, float]] = field(default_factory=list)     # (alphabet key, score)
    prep: int = 0

    def word_text(self, li: int, wi: int) -> str:
        return "".join(self.glyphs[g].char for g in self.lines[li][wi])

    def raw_text(self) -> str:
        return "\n".join(" ".join(self.word_text(li, wi) for wi in range(len(line)))
                         for li, line in enumerate(self.lines))

    def corrected_text(self) -> str:
        if not self.corrected:
            return self.raw_text()
        return "\n".join(" ".join(t for t, _ in line) for line in self.corrected)

    def remove_glyph(self, idx: int) -> None:
        """Drop a glyph (noise picked up as a letter) and renumber the layout."""
        del self.glyphs[idx]
        lines = []
        for line in self.lines:
            words = [[g - (g > idx) for g in w if g != idx] for w in line]
            words = [w for w in words if w]
            if words:
                lines.append(words)
        self.lines = lines


# ------------------------------------------------------------------ binarization

def _odd(v: int) -> int:
    v = int(v)
    return v if v % 2 else v + 1


def _otsu(gray: np.ndarray, region: np.ndarray | None) -> float:
    vals = gray if region is None else gray[region > 0]
    if vals.size < 16:
        vals = gray
    t, _ = cv2.threshold(vals.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(t)


def _border_pixels(gray: np.ndarray, region: np.ndarray | None) -> np.ndarray:
    """Pixels along the edge of the selection — they are usually background."""
    if region is not None and region.any() and not region.all():
        inner = cv2.erode(region, np.ones((5, 5), np.uint8))
        edge = (region > 0) & (inner == 0)
        if edge.sum() >= 16:
            return gray[edge]
    b = max(1, min(gray.shape) // 30)
    return np.concatenate([gray[:b].ravel(), gray[-b:].ravel(), gray[:, :b].ravel(), gray[:, -b:].ravel()])


def guess_polarity(img: np.ndarray, region: np.ndarray | None = None) -> str:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    t = _otsu(gray, region)
    border = np.median(_border_pixels(gray, region))
    if abs(border - t) < 8:
        vals = gray if region is None else gray[region > 0]
        return "light" if (vals > t).mean() < 0.5 else "dark"
    return "light" if border < t else "dark"


def binarize(img: np.ndarray, s: Settings, size_hint: float = 0.0,
             region: np.ndarray | None = None) -> np.ndarray:
    mask = _binarize(img, s, size_hint, region)
    if region is not None:
        mask = cv2.bitwise_and(mask, region)
    return mask


def _binarize(img, s: Settings, size_hint: float, region) -> np.ndarray:
    if s.binarize == "color" and s.color is not None:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
        ref = cv2.cvtColor(np.uint8([[list(s.color)]]), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
        d = np.sqrt(((lab - ref) ** 2).sum(axis=2))
        mask = (d < s.color_tol).astype(np.uint8) * 255
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if max(gray.shape) > 300:
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
    polarity = s.polarity if s.polarity != "auto" else guess_polarity(img, region)

    if s.binarize == "flat":
        # Flatten uneven background (lighting, gradients) with a morphological top-hat first.
        size = size_hint if size_hint > 0 else min(gray.shape) / 4.0
        k = _odd(int(np.clip(0.75 * size, 7, 81)))
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        op = cv2.MORPH_TOPHAT if polarity == "light" else cv2.MORPH_BLACKHAT
        sm = cv2.GaussianBlur(gray, (0, 0), max(0.8, size / 30.0))
        th = cv2.morphologyEx(sm, op, kern).astype(np.float32)
        vals = th if region is None or not region.any() else th[region > 0]
        hi = float(np.percentile(vals, 99.5))
        if hi <= 1:
            return np.zeros_like(gray)
        norm = (np.clip(th / hi, 0, 1) * 255).astype(np.uint8)
        t_flat = _otsu(norm, region)
        # Embossed letters are lit unevenly: a threshold below Otsu keeps the strokes whole.
        mask = ((norm > 0.7 * t_flat) * 255).astype(np.uint8)
        c = max(2, int(round(size / 18.0)))
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (c, c)))
    if s.binarize == "adaptive":
        block = _odd(max(15, min(gray.shape) // 4))
        if polarity == "light":
            return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, -10)
        return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 10)
    t = _otsu(gray, region)
    _, mask = cv2.threshold(gray, t, 255, cv2.THRESH_BINARY if polarity == "light" else cv2.THRESH_BINARY_INV)
    return mask


# ------------------------------------------------------------------ segmentation

@dataclass
class _Comp:
    idx: int
    x: int
    y: int
    w: int
    h: int
    area: int


def _components(mask: np.ndarray):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [_Comp(i, *map(int, stats[i, :5])) for i in range(1, n)]
    comps = [c for c in comps if c.area >= 3]
    if not comps:
        return lab, [], 0.0, 0.0
    H_img, W_img = mask.shape

    def junk(c):    # frame lines of a sign touching the selection border
        on_border = c.x == 0 or c.y == 0 or c.x + c.w >= W_img or c.y + c.h >= H_img
        long_ = c.w > 0.8 * W_img or c.h > 0.8 * H_img or max(c.w, c.h) > 7 * max(1, min(c.w, c.h))
        return on_border and long_ and len(comps) > 1

    comps = [c for c in comps if not junk(c)] or comps
    areas = np.array([c.area for c in comps], np.float32)
    ref = np.percentile(areas, 90)
    big = [c for c in comps if c.area >= 0.18 * ref]
    # Upper percentile: "fragmented" scripts have many small parts (dots, strokes).
    # Width is capped by height so touching glyphs do not inflate the estimate.
    S = float(np.percentile([max(min(c.w, 1.4 * c.h), min(c.h, 1.4 * c.w)) for c in big], 80))
    Hh = float(np.percentile([min(c.h, 1.4 * c.w) for c in big], 80))
    min_area = max(3.0, 0.004 * S * S)
    comps = [c for c in comps if c.area >= min_area and c.h <= 3.2 * S and c.w <= 6 * S]
    return lab, comps, S, Hh


def _split_touching(lab: np.ndarray, comps: list[_Comp], S: float, orientation: str):
    """Cut components that are too long along the line at their narrowest points.

    Extra cuts are harmless: the dynamic program glues the pieces back together when the
    whole looks more like a letter.
    """
    out, new_lab = [], None
    next_id = int(lab.max()) + 1
    for c in comps:
        length, thick = (c.w, c.h) if orientation == "h" else (c.h, c.w)
        if length < 1.3 * S or length < 1.15 * thick:
            out.append(c)
            continue
        sub = lab[c.y:c.y + c.h, c.x:c.x + c.w] == c.idx
        prof = sub.sum(axis=0 if orientation == "h" else 1).astype(np.float32)
        prof_s = np.convolve(prof, np.ones(3) / 3, mode="same")
        lo, hi = int(0.28 * S), len(prof) - int(0.28 * S)
        win = max(2, int(0.18 * S))
        level = 0.45 * float(np.median(prof[prof > 0])) if (prof > 0).any() else 0
        cuts = []
        for x in range(lo, hi):
            seg = prof_s[max(0, x - win):x + win + 1]
            if prof_s[x] <= seg.min() + 1e-6 and prof_s[x] <= level:
                if not cuts or x - cuts[-1] >= 0.3 * S:
                    cuts.append(x)
        cuts = cuts[:6]
        if not cuts:
            out.append(c)
            continue
        if new_lab is None:
            new_lab = lab.copy()
        edges = [0] + cuts + [len(prof)]
        for a, b in zip(edges, edges[1:]):
            part = np.zeros_like(sub)
            if orientation == "h":
                part[:, a:b] = sub[:, a:b]
            else:
                part[a:b, :] = sub[a:b, :]
            ys, xs = np.nonzero(part)
            if len(xs) == 0:
                continue
            new_lab[c.y:c.y + c.h, c.x:c.x + c.w][part] = next_id
            out.append(_Comp(next_id, c.x + int(xs.min()), c.y + int(ys.min()),
                             int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1), int(part.sum())))
            next_id += 1
    return (new_lab if new_lab is not None else lab), out


def apply_transform(m: np.ndarray, t: str) -> np.ndarray:
    if t == "rot180":
        return cv2.rotate(m, cv2.ROTATE_180)
    if t == "flip_h":
        return cv2.flip(m, 1)
    if t == "flip_v":
        return cv2.flip(m, 0)
    return m


def _box_back(x, y, w, h, t, W, H):
    """Box in the transformed image → box in the original image."""
    if t in ("rot180", "flip_h"):
        x = W - (x + w)
    if t in ("rot180", "flip_v"):
        y = H - (y + h)
    return x, y, w, h


def _axes(c: _Comp, orientation: str):
    """(p0, p1, q0, q1): p runs along the line, q across it."""
    if orientation == "h":
        return c.x, c.x + c.w, c.y, c.y + c.h
    return c.y, c.y + c.h, c.x, c.x + c.w


def _lines(comps: list[_Comp], S: float, orientation: str) -> list[list[_Comp]]:
    big = [c for c in comps if max(c.w, c.h) >= 0.5 * S]
    if not big:
        return []
    iv = []
    for c in big:
        _, _, q0, q1 = _axes(c, orientation)
        shrink = (q1 - q0) * 0.18
        iv.append((q0 + shrink, q1 - shrink))
    iv.sort()
    bands = [list(iv[0])]
    for a, b in iv[1:]:
        if a <= bands[-1][1]:
            bands[-1][1] = max(bands[-1][1], b)
        else:
            bands.append([a, b])
    # Very low bands are fragments of letters (loops, dots), not separate lines.
    if len(bands) > 1:
        hs = [b - a for a, b in bands]
        kept = [bd for bd, h in zip(bands, hs) if h >= 0.4 * max(hs) or h >= 0.45 * S]
        bands = kept or bands
    groups: list[list[_Comp]] = [[] for _ in bands]
    for c in comps:
        _, _, q0, q1 = _axes(c, orientation)
        qc = (q0 + q1) / 2
        best, bd = None, 1e9
        for i, (a, b) in enumerate(bands):
            d = 0.0 if a <= qc <= b else min(abs(qc - a), abs(qc - b))
            if d < bd:
                best, bd = i, d
        if best is not None and bd <= 0.75 * S:
            groups[best].append(c)
    order = list(range(len(bands)))
    if orientation == "v_rtl":
        order.reverse()
    return [groups[i] for i in order if groups[i]]


def _group_mask(lab: np.ndarray, members: list[_Comp]):
    x0 = min(c.x for c in members)
    y0 = min(c.y for c in members)
    x1 = max(c.x + c.w for c in members)
    y1 = max(c.y + c.h for c in members)
    m = np.isin(lab[y0:y1, x0:x1], [c.idx for c in members]).astype(np.uint8) * 255
    return m, (x0, y0, x1 - x0, y1 - y0)


class Engine:
    def __init__(self, library: Library | None = None, alphabets_dir: str | None = None,
                 user_words: str | None = None):
        adir = alphabets_dir or paths.alphabets_dir()
        self.alphabets = load_alphabets(adir)
        if not self.alphabets:
            raise RuntimeError(f"No alphabet charts found in {adir}")
        self.library = library if library is not None else Library(paths.builtin_library_dir(),
                                                                    paths.user_library_dir())
        self.classifiers = {a.key: self._build_classifier(a) for a in self.alphabets}
        self.user_words = user_words if user_words is not None else paths.user_words_path()
        self.reload_lexicon()

    def reload_lexicon(self):
        d = paths.data_dir()
        self.lexicon = Lexicon([(os.path.join(d, "genshin_words.txt"), False),
                                (self.user_words, False),
                                (os.path.join(d, "words_en.txt"), True)])

    def _build_classifier(self, a: Alphabet) -> Classifier:
        return Classifier(a.templates + self.library.templates_for(a.key))

    def rebuild(self, key: str | None = None):
        for a in self.alphabets:
            if key is None or a.key == key:
                self.classifiers[a.key] = self._build_classifier(a)

    def alphabet(self, key: str) -> Alphabet:
        return next(a for a in self.alphabets if a.key == key)

    # -------------------------------------------------------------- learning
    def glyph_mask(self, r: Result, idx: int) -> np.ndarray | None:
        """Binary image of a recognized glyph, upright (rotation/mirror undone)."""
        g = r.glyphs[idx]
        src, k = (r.work_mask, r.scale) if r.work_mask is not None else (r.mask, 1.0)
        if src is None:
            return None
        piece = src[int(g.y * k):int(np.ceil((g.y + g.h) * k)), int(g.x * k):int(np.ceil((g.x + g.w) * k))]
        if piece.size == 0 or piece.max() == 0:
            return None
        return apply_transform(piece, r.transform)

    def learn(self, r: Result, items: list[tuple[int, str]], rebuild: bool = True) -> int:
        """Save glyphs of a result as library samples: items = [(glyph index, char or NOISE)]."""
        n = 0
        for idx, char in items:
            m = self.glyph_mask(r, idx)
            if m is None:
                continue
            rel = r.glyphs[idx].h / r.size_ref if r.size_ref > 0 else 1.0
            if self.library.add(r.alphabet.key, char, m, rel) is not None:
                n += 1
        if n and rebuild:
            self.rebuild(r.alphabet.key)
        return n

    # -------------------------------------------------------------- main entry
    def recognize(self, img: np.ndarray, s: Settings, offset=(0, 0),
                  region: np.ndarray | None = None) -> Result | None:
        """Recognize text in ``img`` (BGR). ``region`` (uint8, same size) limits it to a free-form area.

        Stage 1: every mask variant × every alphabet without rotation; then rotations/mirrors
        for every mask variant; the dictionary is applied to the ten best readings only.
        """
        if region is not None and not region.any():
            return None
        if s.binarize == "color":
            variants = [replace(s, binarize="color")]
        else:
            bins = list(BINARIZATIONS) if s.binarize == "auto" else [s.binarize]
            if s.polarity == "auto":
                first = guess_polarity(img, region)
                pols = [first, "dark" if first == "light" else "light"]
            else:
                pols = [s.polarity]
            variants = [replace(s, binarize=b, polarity=p) for p in pols for b in bins]
        keys = [a.key for a in self.alphabets] if s.alphabet == "auto" else [s.alphabet]
        transforms = list(TRANSFORMS) if s.transform == "auto" else [s.transform]

        prepared = []
        for v in variants:
            mask = binarize(img, v, 0.0, region)
            _, comps0, S0, _ = _components(mask)
            if not comps0:
                continue
            hint = 0.0
            if v.binarize == "flat":       # second pass with the kernel sized to the found glyphs
                hint = S0
                mask = binarize(img, v, hint, region)
                _, comps0, S0, _ = _components(mask)
                if not comps0:
                    continue
            scale, work = 1.0, mask
            # Small text: upscale so binarization does not eat the details.
            if S0 < 30 and max(img.shape[:2]) * (40.0 / S0) < 5000:
                scale = 40.0 / S0
                big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                big_region = None if region is None else cv2.resize(
                    region, (big.shape[1], big.shape[0]), interpolation=cv2.INTER_NEAREST)
                work = binarize(big, v, (hint or S0) * scale, big_region)
            prepared.append((v, mask, work, scale))

        first_t = transforms[0] if len(transforms) == 1 else "none"
        results = []
        for pi, (v, mask, work, scale) in enumerate(prepared):
            results += self._run(pi, mask, work, scale, first_t, keys, s, offset)
        if not results:
            return None
        if len(transforms) > 1:
            # Mirrored text of one alphabet often "looks like" another alphabet without
            # mirroring, so rotations are tried for every mask and every alphabet.
            for pi, (v, mask, work, scale) in enumerate(prepared):
                for t in transforms:
                    if t != first_t:
                        results += self._run(pi, mask, work, scale, t, keys, s, offset)
        results.sort(key=self._rank, reverse=True)
        results = results[:10]
        for r in results:
            self.apply_dictionary(r, s.use_dictionary)
        scored = sorted(((self._rank(r), r) for r in results), key=lambda t: -t[0])
        if os.environ.get("GST_DEBUG"):
            for sc, r in scored[:8]:
                v = prepared[r.prep][0]
                print(f"  {sc:.3f} q={r.quality:.3f} n={len(r.glyphs)} {v.binarize}/{v.polarity}/"
                      f"{r.transform} {r.alphabet.key}: {r.corrected_text()!r}")
        best = scored[0][1]
        alt: dict[str, float] = {}
        for sc, r in scored:
            alt.setdefault(r.alphabet.key, sc)
        best.alternatives = sorted(alt.items(), key=lambda t: -t[1])
        return best

    def _run(self, prep_idx, mask, work, scale, t, keys, s: Settings, offset) -> list[Result]:
        Hw, Ww = work.shape
        lab, comps, S, Hh = _components(apply_transform(work, t))
        if not comps:
            return []
        orients = [self.guess_orientation(comps, S)] if s.orientation == "auto" else [s.orientation]
        out = []
        for o in orients:
            lab_o, comps_o = _split_touching(lab, comps, S, o)
            lines = _lines(comps_o, S, o)
            cache: dict = {}
            for k in keys:
                r = self._recognize_lines(lab_o, lines, S, Hh, o, k, s, cache)
                if r is None:
                    continue
                r.transform = t
                r.mask = mask if scale == 1.0 else ((cv2.resize(
                    work, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_AREA) > 100) * 255).astype(np.uint8)
                r.offset = offset
                r.size_ref = Hh / scale
                r.work_mask, r.scale = work, scale
                r.prep = prep_idx
                for g in r.glyphs:
                    x, y, w, h = _box_back(g.x, g.y, g.w, g.h, t, Ww, Hw)
                    x0, y0 = int(x / scale), int(y / scale)
                    x1, y1 = int(np.ceil((x + w) / scale)), int(np.ceil((y + h) / scale))
                    g.x, g.y, g.w, g.h = x0, y0, max(1, x1 - x0), max(1, y1 - y0)
                out.append(r)
        return out

    @staticmethod
    def guess_orientation(comps, S) -> str:
        """Pick the direction with more signs per line (fewer lines)."""
        nh = len(_lines(comps, S, "h"))
        nv = len(_lines(comps, S, "v_rtl"))
        return "v_rtl" if nv < 0.6 * nh else "h"

    def _rank(self, r: Result) -> float:
        if r.corrected:
            words = [t for line in r.corrected for t, _ in line]
        else:
            words = [r.word_text(li, wi) for li, line in enumerate(r.lines) for wi in range(len(line))]
        letters = sum(len(w) for w in words)
        # Short words (AM, AND) are easily "found" in garbage, so they weigh less.
        weight = {2: 0.25, 3: 0.5}
        hit_letters = sum(len(w) * weight.get(len(w), 1.0) for w in words if len(w) >= 2 and w in self.lexicon)
        hit = hit_letters / letters if letters else 0.0
        prior = 0.04 if r.transform == "none" else 0.0
        # "IIIIIII" is suspicious: a stick-like letter fits any stroke.
        chars = [g.char for g in r.glyphs]
        if len(chars) >= 4:
            top_frac = max(chars.count(c) for c in set(chars)) / len(chars)
            prior -= 0.3 * max(0.0, top_frac - 0.3)
        # Slightly favour readings with more letters, otherwise masks that kept only a couple
        # of clean signs would win.
        return r.quality + 0.10 * hit + prior + 0.015 * np.log1p(min(len(r.glyphs), 40))

    # -------------------------------------------------------------- lines → glyphs
    def _recognize_lines(self, lab, lines, S, Hh, orientation, key, s: Settings, cache) -> Result | None:
        cls = self.classifiers[key]
        cols = cls.letter_columns
        glyphs: list[Glyph] = []
        line_glyphs: list[list[int]] = []
        gaps_all: list[float] = []
        total_ink, total_score = 0.0, 0.0
        for line in lines:
            line = sorted(line, key=lambda c: sum(_axes(c, orientation)[:2]))
            n = len(line)
            cand, feats, metas = {}, [], []
            for i in range(n):
                for j in range(i + 1, min(n, i + s.max_group) + 1):
                    members = line[i:j]
                    ax = [_axes(c, orientation) for c in members]
                    p0, p1 = min(a[0] for a in ax), max(a[1] for a in ax)
                    q0, q1 = min(a[2] for a in ax), max(a[3] for a in ax)
                    if j - i > 1:
                        srt = sorted(ax)
                        run, bad = srt[0][1], False
                        for a in srt[1:]:
                            if a[0] - run > 0.42 * S:      # gap inside the group is too wide
                                bad = True
                                break
                            run = max(run, a[1])
                        if bad or p1 - p0 > 1.75 * S or q1 - q0 > 1.9 * S:
                            break
                    ck = (orientation, tuple(c.idx for c in members))
                    if ck not in cache:
                        m, box = _group_mask(lab, members)
                        cache[ck] = (features(m), box, int(sum(c.area for c in members)))
                    f, box, ink = cache[ck]
                    cand[(i, j)] = len(feats)
                    feats.append(f)
                    metas.append((box, ink))
            if not feats:
                continue
            sc_all = cls.scores(np.stack(feats))
            rel_h = np.array([m[0][3] / max(Hh, 1.0) for m in metas], np.float32)
            sc_all = sc_all - 0.22 * cls.height_penalty(rel_h)
            is_noise = (np.argmax(sc_all, axis=1) == cls.noise_index) if cls.noise_index is not None \
                else np.zeros(len(feats), bool)
            sc = sc_all[:, cols]
            best_c = sc.max(axis=1)
            line_ink = float(sum(c.area for c in line))
            n_big = max(1, sum(1 for c in line if max(c.w, c.h) >= 0.5 * S))
            glyph_pen = 0.12 / n_big
            # Dynamic program over ways to split the line into glyphs.
            dp = np.full(n + 1, -1e18)
            back = np.zeros(n + 1, np.int32)
            skip = np.full(n + 1, False)
            dp[0] = 0.0
            for j in range(1, n + 1):
                c = line[j - 1]
                # A tiny speck may be dropped as noise (small penalty for the lost ink).
                if max(c.w, c.h) < 0.25 * S and dp[j - 1] > -1e17:
                    v = dp[j - 1] - 0.3 * c.area / line_ink
                    if v > dp[j]:
                        dp[j], back[j], skip[j] = v, j - 1, True
                for i in range(max(0, j - s.max_group), j):
                    k = cand.get((i, j))
                    if k is None or dp[i] <= -1e17:
                        continue
                    if is_noise[k]:
                        # looks like a learned noise sample: may only be dropped
                        v, drop = dp[i], True
                    else:
                        v, drop = dp[i] + metas[k][1] / line_ink * best_c[k] - glyph_pen, False
                    if v > dp[j]:
                        dp[j], back[j], skip[j] = v, i, drop
            if dp[n] <= -1e17:
                continue
            segs = []
            j = n
            while j > 0:
                i = int(back[j])
                if not skip[j]:
                    segs.append(cand[(i, j)])
                j = i
            segs.reverse()
            if not segs:
                continue
            idxs, prev_p1 = [], None
            for k in segs:
                (x, y, w, h), ink = metas[k]
                glyphs.append(Glyph(x, y, w, h, sc[k].copy(), cls.letters[int(np.argmax(sc[k]))]))
                idxs.append(len(glyphs) - 1)
                p0, p1 = (x, x + w) if orientation == "h" else (y, y + h)
                if prev_p1 is not None:
                    gaps_all.append(p0 - prev_p1)
                prev_p1 = p1
                total_ink += ink
                total_score += ink * float(sc[k].max())
            line_glyphs.append(idxs)
        if not glyphs:
            return None

        thr = self._space_threshold(gaps_all, S, s.space_factor)
        lines_out = []
        for idxs in line_glyphs:
            words, cur = [], [idxs[0]]
            for a, b in zip(idxs, idxs[1:]):
                ga, gb = glyphs[a], glyphs[b]
                gap = (gb.x - (ga.x + ga.w)) if orientation == "h" else (gb.y - (ga.y + ga.h))
                if gap > thr:
                    words.append(cur)
                    cur = [b]
                else:
                    cur.append(b)
            words.append(cur)
            lines_out.append(words)
        return Result(self.alphabet(key), list(cls.letters), orientation, "none", glyphs, lines_out,
                      total_score / max(total_ink, 1.0), None)

    @staticmethod
    def _space_threshold(gaps: list[float], S: float, factor: float) -> float:
        if factor > 0:
            return factor * S
        g = np.array([x for x in gaps if x > -0.2 * S], np.float32)
        if len(g) < 2:
            return 0.6 * S
        med = float(np.median(np.clip(g, 0, None)))
        # a space is a gap clearly wider than the usual gap between letters
        return max(1.9 * med + 0.08 * S, 0.33 * S)

    # -------------------------------------------------------------- dictionary
    def apply_dictionary(self, r: Result, enabled: bool = True):
        r.corrected = []
        if not r.alphabet.spec.english:     # e.g. Inazuma: romanized Japanese, not English
            enabled = False
        for li, line in enumerate(r.lines):
            if not enabled:
                r.corrected.append([(r.word_text(li, wi), False) for wi in range(len(line))])
                continue
            words = []
            for word in line:
                scores = np.stack([r.glyphs[g].scores for g in word])
                locked = {i: r.glyphs[g].char for i, g in enumerate(word) if r.glyphs[g].manual}
                words.append((scores, "".join(r.glyphs[g].char for g in word), locked))
            r.corrected.append(self.lexicon.decode_line(words, r.chars))


__all__ = ["Engine", "Settings", "Result", "Glyph", "TRANSFORMS", "ORIENTATIONS", "BINARIZATIONS",
           "NOISE", "binarize", "guess_polarity", "apply_transform"]
