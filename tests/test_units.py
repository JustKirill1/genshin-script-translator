"""Selection masks, the dictionary line decoder, history and settings."""
import tempfile

import numpy as np

from genshin_script_translator.history import History
from genshin_script_translator.lexicon import Lexicon
from genshin_script_translator.selection import ADD, SUB, Selection, Shape
from genshin_script_translator.settings import AppSettings

LETTERS = [chr(65 + i) for i in range(26)]


def test_selection_mask_and_bbox():
    sel = Selection([Shape.rect(10, 10, 50, 30)])
    assert sel.is_plain_rect()
    assert sel.bbox(100, 100) == (10, 10, 50, 30)
    sel.shapes.append(Shape.rect(10, 10, 30, 30, SUB))
    assert not sel.is_plain_rect()
    m = sel.mask((10, 10, 50, 30))
    assert m.shape == (20, 40)
    assert m[:, :18].max() == 0 and m[:, 25:].min() == 255
    lasso = Selection([Shape(ADD, [(0, 0), (40, 0), (0, 40)])])
    m = lasso.mask(lasso.bbox(100, 100))
    assert m[2, 2] == 255 and m[38, 38] == 0
    assert Selection.from_json(sel.to_json()).to_json() == sel.to_json()
    assert Selection().is_empty() and Selection().bbox(10, 10) is None


def _scores(word: str, doubt: dict | None = None) -> np.ndarray:
    s = np.full((len(word), 26), 0.4, np.float32)
    for i, ch in enumerate(word):
        s[i, ord(ch) - 65] = 0.9
    for i, (ch, v) in (doubt or {}).items():
        s[i, ord(ch) - 65] = v
    return s


def _lexicon(words):
    path = tempfile.mktemp(suffix=".txt")
    with open(path, "w") as f:
        f.write("\n".join(words))
    return Lexicon([(path, False)])


def test_decoder_splits_and_merges_words():
    lex = _lexicon(["SMITH", "SHOP", "THOSE", "WHO", "DO", "FINE", "FOOD", "SCHULZ"])
    out = lex.decode_line([(_scores("SMITHSHOP"), "SMITHSHOP", {})], LETTERS)
    assert [t for t, _ in out] == ["SMITH", "SHOP"]
    words = [(_scores("THOS"), "THOS", {}), (_scores("EWHODO"), "EWHODO", {})]
    assert [t for t, _ in lex.decode_line(words, LETTERS)] == ["THOSE", "WHO", "DO"]
    # a doubtful letter is corrected, a confident wrong one is not
    doubtful = _scores("FINC", {3: ("E", 0.85)})
    assert lex.decode_line([(doubtful, "FINC", {})], LETTERS)[0] == ("FINE", True)
    assert lex.decode_line([(_scores("FINC"), "FINC", {})], LETTERS)[0] == ("FINC", False)
    # unknown names stay whole
    assert lex.decode_line([(_scores("DAMORVILLE"), "DAMORVILLE", {})], LETTERS)[0][0] == "DAMORVILLE"


def test_history_roundtrip():
    folder = tempfile.mkdtemp()
    h = History(folder, limit=2)
    img = np.zeros((50, 80, 3), np.uint8)
    sel = Selection([Shape.rect(5, 5, 40, 30)])
    e1 = h.add(img, "HELLO", "HELL0", "common", sel, (5, 5, 40, 30))
    h.add(img, "WORLD", "WORLD", "common", None)
    h.add(img, "THIRD", "THIRD", "fontaine", None)
    assert [e.text for e in h.entries] == ["THIRD", "WORLD"]            # limit applied, newest first
    h2 = History(folder, limit=5)
    assert len(h2.entries) == 2 and h2.image(h2.entries[0]).shape == img.shape
    h2.update(h2.entries[0].id, "CHANGED", "CHANGED")
    assert History(folder).entries[0].text == "CHANGED"
    assert e1.id not in {e.id for e in h2.entries}
    h2.clear()
    assert History(folder).entries == []


def test_settings_roundtrip():
    path = tempfile.mktemp(suffix=".json")
    s = AppSettings(language="ru", history_limit=50, author="Kirill")
    s.save(path)
    t = AppSettings.load(path)
    assert (t.language, t.history_limit, t.author) == ("ru", 50, "Kirill")
    assert AppSettings.load(path + ".missing").language == "en"
