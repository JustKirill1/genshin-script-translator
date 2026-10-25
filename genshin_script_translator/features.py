"""Glyph features and a template classifier with augmentation."""
from __future__ import annotations

import hashlib

import cv2
import numpy as np

NORM = 32          # side of the normalized glyph image
PIX = 16           # side of the downscaled copy used as "pixel" features
CELLS = 4          # grid of cells for gradient histograms
BINS = 8           # gradient directions (0..360)

NOISE = "~"        # pseudo-character for learned "not a letter" samples


def normalize(mask: np.ndarray) -> np.ndarray:
    """Crop to content and fit into a square keeping the aspect ratio → float NORM×NORM."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return np.zeros((NORM, NORM), np.float32)
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32) / 255.0
    h, w = m.shape
    side = max(h, w)
    pad = int(round(side * 0.08)) + 1
    canvas = np.zeros((side + 2 * pad, side + 2 * pad), np.float32)
    oy, ox = pad + (side - h) // 2, pad + (side - w) // 2
    canvas[oy:oy + h, ox:ox + w] = m
    interp = cv2.INTER_AREA if canvas.shape[0] > NORM else cv2.INTER_LINEAR
    out = cv2.resize(canvas, (NORM, NORM), interpolation=interp)
    return cv2.GaussianBlur(out, (3, 3), 0.8)


def _hog(img: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    ang = (np.arctan2(gy, gx) + np.pi) / (2 * np.pi) * BINS  # 0..BINS
    b0 = np.floor(ang).astype(np.int32) % BINS
    b1 = (b0 + 1) % BINS
    w1 = ang - np.floor(ang)
    w0 = 1.0 - w1
    cs = NORM // CELLS
    feat = np.zeros((CELLS, CELLS, BINS), np.float32)
    for cy in range(CELLS):
        for cx in range(CELLS):
            sl = (slice(cy * cs, (cy + 1) * cs), slice(cx * cs, (cx + 1) * cs))
            m = mag[sl].ravel()
            np.add.at(feat[cy, cx], b0[sl].ravel(), m * w0[sl].ravel())
            np.add.at(feat[cy, cx], b1[sl].ravel(), m * w1[sl].ravel())
    f = feat.ravel()
    n = np.linalg.norm(f)
    return f / n if n > 0 else f


def features(mask: np.ndarray) -> np.ndarray:
    img = normalize(mask)
    pix = cv2.resize(img, (PIX, PIX), interpolation=cv2.INTER_AREA).ravel()
    pix = pix - pix.mean()
    n = np.linalg.norm(pix)
    pix = pix / n if n > 0 else pix
    hog = _hog(img)
    f = np.concatenate([pix * 0.55, hog * 0.83])
    n = np.linalg.norm(f)
    return (f / n if n > 0 else f).astype(np.float32)


# ---------------------------------------------------------------- augmentation

def warp(mask: np.ndarray, angle: float, shear: float, sx: float) -> np.ndarray:
    h, w = mask.shape
    pad = int(max(h, w) * 0.3) + 2
    m = cv2.copyMakeBorder(mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    H, W = m.shape
    c = (W / 2, H / 2)
    A = np.vstack([cv2.getRotationMatrix2D(c, angle, 1.0), [0, 0, 1]])
    S = np.array([[sx, shear, (1 - sx) * c[0] - shear * c[1]], [0, 1, 0], [0, 0, 1]], np.float32)
    out = cv2.warpAffine(m, (S @ A)[:2], (W, H), flags=cv2.INTER_LINEAR)
    return ((out > 127) * 255).astype(np.uint8)


def thickness(mask: np.ndarray, delta: int) -> np.ndarray:
    if delta == 0:
        return mask
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(delta) + 1, 2 * abs(delta) + 1))
    pad = abs(delta) + 1
    m = cv2.copyMakeBorder(mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    return cv2.dilate(m, k) if delta > 0 else cv2.erode(m, k)


def _lowres(mask: np.ndarray, target_h: int) -> np.ndarray:
    h, w = mask.shape
    s = target_h / h
    small = cv2.resize(mask, (max(1, int(round(w * s))), target_h), interpolation=cv2.INTER_AREA)
    return ((small > 110) * 255).astype(np.uint8)


def augment(mask: np.ndarray, rng: np.random.Generator, n: int = 26) -> list[np.ndarray]:
    """Simulate game rendering: slant, rotation, stroke width, low resolution."""
    out = [mask, _lowres(mask, 20), _lowres(mask, 14)]
    stroke = max(1, int(round(mask.shape[0] * 0.035)))
    for _ in range(n):
        m = warp(mask, rng.uniform(-7, 7), rng.uniform(-0.18, 0.18), rng.uniform(0.85, 1.15))
        m = thickness(m, int(rng.choice([-stroke, 0, 0, stroke, 2 * stroke if stroke > 1 else stroke])))
        if rng.random() < 0.35:
            m = _lowres(m, int(rng.integers(12, 26)))
        if m.max() > 0:
            out.append(m)
    return out


# Augmented features are cached per template image, so rebuilding a classifier after
# learning one more glyph only processes the new sample.
_FEATURE_CACHE: dict[str, np.ndarray] = {}


def _template_features(mask: np.ndarray) -> np.ndarray:
    key = hashlib.sha1(mask.tobytes() + str(mask.shape).encode()).hexdigest()
    f = _FEATURE_CACHE.get(key)
    if f is None:
        rng = np.random.default_rng(int(key[:8], 16))
        f = np.stack([features(m) for m in augment(mask, rng)])
        _FEATURE_CACHE[key] = f
    return f


class Classifier:
    """Nearest neighbour (max cosine similarity) over augmented templates of one alphabet.

    Learned "noise" samples form their own pseudo-class (``NOISE``); the recognizer drops
    glyph candidates that look most like noise. ``letters`` lists the real characters only.
    """

    def __init__(self, templates):
        self.chars = sorted({t.char for t in templates})
        self.char_index = {c: i for i, c in enumerate(self.chars)}
        self.noise_index = self.char_index.get(NOISE)
        self.letter_columns = np.array([i for i, c in enumerate(self.chars) if c != NOISE], np.int64)
        self.letters = [self.chars[i] for i in self.letter_columns]
        feats, labels = [], []
        rel = {i: [] for i in range(len(self.chars))}
        for t in templates:
            ci = self.char_index[t.char]
            rel[ci].append(t.rel_height)
            f = _template_features(t.mask)
            feats.append(f)
            labels.extend([ci] * len(f))
        labels = np.array(labels)
        order = np.argsort(labels, kind="stable")
        self.F = np.concatenate(feats)[order]
        self.labels = labels[order]
        self.starts = np.searchsorted(self.labels, np.arange(len(self.chars)))
        # log of the relative height of every template of a character (Inazuma S and I have two)
        k = max(len(v) for v in rel.values())
        self.log_rel = np.full((len(self.chars), k), np.nan, np.float32)
        for ci, v in rel.items():
            self.log_rel[ci, :len(v)] = np.log(np.maximum(v, 1e-3))

    def height_penalty(self, rel_h: np.ndarray) -> np.ndarray:
        """rel_h: (n,) relative heights of found glyphs → (n, n_chars) |log| mismatch."""
        d = np.abs(np.log(np.maximum(rel_h, 1e-3))[:, None, None] - self.log_rel[None])
        return np.nanmin(d, axis=2)

    def scores(self, feats: np.ndarray) -> np.ndarray:
        """feats: (n, d) → (n, n_chars) best similarity to each character (including noise)."""
        sims = feats @ self.F.T                      # (n, n_variants)
        return np.maximum.reduceat(sims, self.starts, axis=1)
