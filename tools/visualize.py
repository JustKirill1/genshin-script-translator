"""Debug view: annotated image plus the letter mask.

    python tools/visualize.py screenshot.png out.png [x0 y0 x1 y1] [setting=value ...]
    e.g. python tools/visualize.py tests/real/fontaine3.png out.png binarize=flat alphabet=fontaine
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from genshin_script_translator.alphabets import imread_unicode  # noqa: E402
from genshin_script_translator.recognizer import Engine, Settings  # noqa: E402
from genshin_script_translator.render import render_annotated  # noqa: E402


def main(argv):
    img = imread_unicode(argv[0])
    nums = [int(a) for a in argv[2:] if a.lstrip("-").isdigit()]
    kv = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
    box = tuple(nums) if len(nums) == 4 else (0, 0, img.shape[1], img.shape[0])
    s = Settings()
    for k, v in kv.items():
        t = type(getattr(s, k))
        setattr(s, k, v if t is str else t(v))
    x0, y0, x1, y1 = box
    r = Engine().recognize(img[y0:y1, x0:x1], s, offset=(x0, y0))
    if r is None:
        print("nothing found")
        return
    print(r.alphabet.key, f"{r.quality:.2f}", r.orientation, r.transform)
    print(r.corrected_text())
    for g in r.glyphs:
        print(g.char, [(c, round(v, 2)) for c, v in g.candidates(r.chars, 3)])
    view = render_annotated(img, r, box, r.alphabet.title)
    m = cv2.cvtColor(r.mask, cv2.COLOR_GRAY2BGR)
    m = cv2.resize(m, (view.shape[1], int(m.shape[0] * view.shape[1] / m.shape[1])), interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(argv[1], np.vstack([view, m]))


if __name__ == "__main__":
    main(sys.argv[1:])
