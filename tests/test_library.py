"""Glyph library: storage, relabel/delete, .gsrlib sharing, legacy import and the noise class."""
import json
import os
import tempfile

import cv2
import numpy as np

from genshin_script_translator.features import NOISE
from genshin_script_translator.library import BUILTIN, IMPORTED, USER, Library
from genshin_script_translator.recognizer import Engine, Settings
from synth import render


def _mask(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    m = np.zeros((40, 30), np.uint8)
    for _ in range(4):
        x0, y0 = rng.integers(0, 25), rng.integers(0, 35)
        cv2.line(m, (int(x0), int(y0)), (int(rng.integers(0, 30)), int(rng.integers(0, 40))), 255, 3)
    return m


def _libs():
    builtin = tempfile.mkdtemp()
    user = tempfile.mkdtemp()
    seed = Library(builtin, tempfile.mkdtemp())
    seed.save_builtin_from([("common", "A", _mask(1), 1.0), ("common", "B", _mask(2), 1.1)])
    return Library(builtin, user), builtin, user


def test_add_dedupe_relabel_remove():
    lib, builtin, user = _libs()
    assert lib.count() == 2 and lib.count(source=BUILTIN) == 2
    s = lib.add("common", "C", _mask(3), 0.9)
    assert s is not None and s.source == USER
    assert lib.add("common", "C", _mask(3), 0.9) is None        # same image again
    s = lib.relabel(s.id, "D")
    assert s.char == "D" and os.path.isfile(lib.path_of(s))
    # built-in: relabel copies to the user library and hides the original
    b = [x for x in lib.samples() if x.source == BUILTIN][0]
    copy = lib.relabel(b.id, "Z")
    assert copy is not None and copy.source == USER and b.id in lib.hidden_builtin
    assert lib.remove(s.id)
    reopened = Library(builtin, user)                             # state survives a restart
    assert reopened.count(source=BUILTIN) == 1 and reopened.count(source=USER) == 1
    assert reopened.restore_builtin() == 1 and reopened.count(source=BUILTIN) == 2


def test_export_import_roundtrip():
    lib, _, _ = _libs()
    lib.add("common", "C", _mask(3), 0.9)
    lib.add("common", NOISE, _mask(4), 0.5)
    lib.add("fontaine", "E", _mask(5), 1.0)
    path = os.path.join(tempfile.mkdtemp(), "x.gsrlib")
    assert lib.export(path, author="Traveler") == 3                 # built-ins excluded by default
    info = Library.read_manifest(path)
    assert info["author"] == "Traveler" and info["noise"] == 1 and info["per_alphabet"] == {"common": 2, "fontaine": 1}

    other = Library(tempfile.mkdtemp(), tempfile.mkdtemp())
    assert other.import_package(path, include_noise=False, alphabets=["common"]) == (1, 0)
    assert other.import_package(path) == (2, 1)
    assert {s.source for s in other.samples()} == {IMPORTED}
    assert {s.author for s in other.samples()} == {"Traveler"}


def test_legacy_index_import():
    folder = tempfile.mkdtemp()
    os.makedirs(os.path.join(folder, "sumeru"))
    cv2.imwrite(os.path.join(folder, "sumeru", "E_1.png"), _mask(7))
    with open(os.path.join(folder, "index.json"), "w") as f:
        json.dump([{"alphabet": "sumeru", "char": "E", "file": "sumeru/E_1.png", "rel_height": 0.8}], f)
    lib = Library(tempfile.mkdtemp(), tempfile.mkdtemp())
    assert Library.read_manifest(os.path.join(folder, "index.json"))["total"] == 1
    assert lib.import_package(os.path.join(folder, "index.json")) == (1, 0)
    assert lib.samples()[0].source == USER


def test_learned_noise_is_dropped():
    lib = Library(tempfile.mkdtemp(), tempfile.mkdtemp())
    eng = Engine(lib)
    img, truth = render(eng.alphabet("common"), "HELLO WORLD", np.random.default_rng(5), height=40)
    # add a letter-sized junk mark after the text
    h, w = img.shape[:2]
    cx = w - 25
    pts = np.array([[cx - 14, h // 2 + 16], [cx + 14, h // 2 + 16], [cx, h // 2 - 18]], np.int32)
    canvas = cv2.copyMakeBorder(img, 0, 0, 0, 40, cv2.BORDER_REPLICATE)
    cv2.fillPoly(canvas, [pts + [40, 0]], (200, 225, 240))
    cv2.circle(canvas, (cx + 40, h // 2), 5, (40, 35, 30), -1)
    before = eng.recognize(canvas, Settings(alphabet="common", transform="none"))
    junk = max(range(len(before.glyphs)), key=lambda i: before.glyphs[i].x)
    assert eng.learn(before, [(junk, NOISE)]) == 1
    after = eng.recognize(canvas, Settings(alphabet="common", transform="none"))
    assert len(after.glyphs) == len(before.glyphs) - 1
    assert NOISE not in after.chars
