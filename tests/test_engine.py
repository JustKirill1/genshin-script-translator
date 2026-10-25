"""Recognition on synthetic phrases built from chart glyphs and on real screenshots."""
import os

import cv2
import numpy as np
import pytest

from genshin_script_translator.recognizer import Settings
from synth import cer, render

REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "real")

PHRASES = ["THE WIND WILL GUIDE YOU HOME", "FRESH FISH AND MEAT SOLD HERE"]


@pytest.mark.parametrize("key", ["common", "inazuma", "sumeru", "deshret", "fontaine", "ancient", "nodkrai"])
def test_synthetic_phrases(bare_engine, key):
    alpha = bare_engine.alphabet(key)
    rng = np.random.default_rng(sum(map(ord, key)))
    errors = []
    for i, phrase in enumerate(PHRASES):
        img, truth = render(alpha, phrase, rng, height=32, light=bool(i % 2))
        r = bare_engine.recognize(img, Settings())
        assert r is not None
        assert r.alphabet.key == key, f"detected {r.alphabet.key}"
        errors.append(cer(truth, r.corrected_text()))
    assert np.mean(errors) <= 0.08, errors


def test_vertical_inazuma(bare_engine):
    img, truth = render(bare_engine.alphabet("inazuma"), "WELCOME TO THE CITY", np.random.default_rng(3),
                        height=32, vertical=True)
    r = bare_engine.recognize(img, Settings())
    assert r.orientation.startswith("v")
    assert cer(truth, r.corrected_text()) <= 0.1


REAL_CASES = [
    ("fontaine2.png", (30, 28, 410, 82), "FRAGRANCES"),
    ("fontaine3.png", None, "THOSE WHO DO NOT WORK SHALL NOT EAT"),
    ("mond1.png", (70, 80, 280, 130), "OPEN"),
    ("mond1.png", (50, 148, 270, 188), "FINE FOOD"),
    ("mond2.png", (40, 35, 355, 92), "SCHULZ"),
    ("mond2.png", (95, 92, 330, 118), "SMITH SHOP"),
]


def _load(name, crop):
    img = cv2.imread(os.path.join(REAL, name))
    if crop:
        x0, y0, x1, y1 = crop
        img = img[y0:y1, x0:x1]
    return img


@pytest.mark.parametrize("name,crop,truth", REAL_CASES)
def test_real_screenshots(engine, name, crop, truth):
    r = engine.recognize(_load(name, crop), Settings())
    assert r is not None and r.transform == "none"
    assert cer(truth, r.corrected_text()) <= 0.1, r.corrected_text()


@pytest.mark.parametrize("flip", ["flip_h", "rot180"])
def test_mirrored_sign(engine, flip):
    img = _load("mond2.png", (40, 35, 355, 92))
    img = cv2.flip(img, 1) if flip == "flip_h" else cv2.rotate(img, cv2.ROTATE_180)
    r = engine.recognize(img, Settings())
    assert r.transform == flip
    assert cer("SCHULZ", r.corrected_text()) <= 0.2


def test_region_mask_limits_recognition(engine):
    img = _load("mond2.png", (95, 92, 330, 118))
    region = np.zeros(img.shape[:2], np.uint8)
    region[:, img.shape[1] // 2:] = 255            # keep only the right half ("SHOP")
    full = engine.recognize(img, Settings())
    half = engine.recognize(img, Settings(), region=region)
    assert 0 < len(half.glyphs) < len(full.glyphs)
    assert all(g.x + g.w // 2 >= img.shape[1] // 2 - 2 for g in half.glyphs)


def test_remove_glyph_renumbers(engine):
    r = engine.recognize(_load("mond2.png", (95, 92, 330, 118)), Settings())
    n = len(r.glyphs)
    first = r.glyphs[1].char
    r.remove_glyph(0)
    assert len(r.glyphs) == n - 1 and r.glyphs[0].char == first
    assert all(0 <= g < n - 1 for line in r.lines for w in line for g in w)
