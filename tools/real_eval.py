"""Accuracy on the real screenshots in tests/real: without learned samples, with the built-in library,
and leave-one-out (learn from all inscriptions except the tested one). Each case is also tried
mirrored and upside down.

    python tools/real_eval.py
"""
import os
import sys
import tempfile

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

from genshin_script_translator.library import Library  # noqa: E402
from genshin_script_translator.recognizer import Engine, Settings  # noqa: E402
from synth import cer  # noqa: E402
from teach_cases import CASES, load  # noqa: E402


def teach(eng, cases):
    for name, crop, key, truth in cases:
        r = eng.recognize(load(name, crop), Settings(alphabet=key, transform="none"))
        lines = [[g for w in line for g in w] for line in r.lines]
        if [len(x) for x in lines] == [len(t) for t in truth]:
            eng.learn(r, [(g, ch) for ln, t in zip(lines, truth) for g, ch in zip(ln, t)], rebuild=False)
    eng.rebuild()


def main():
    variants = (("upright", lambda im: im), ("mirrored", lambda im: cv2.flip(im, 1)),
                ("rot180", lambda im: cv2.rotate(im, cv2.ROTATE_180)))
    totals = {}
    for mode in ("none", "loo"):
        errs = []
        for i, (name, crop, key, truth) in enumerate(CASES):
            eng = Engine(Library(tempfile.mkdtemp(), tempfile.mkdtemp()))
            if mode == "loo":
                teach(eng, CASES[:i] + CASES[i + 1:])
            for vname, f in variants:
                r = eng.recognize(f(load(name, crop)), Settings())
                out = r.corrected_text().replace("\n", " ") if r else ""
                errs.append(cer(" ".join(truth), out))
                print(f"{mode:4s} {name:14s} {vname:8s} {r.alphabet.key if r else '-':8s} cer={errs[-1]:.2f} {out!r}")
        totals[mode] = np.mean(errs)
    print(f"\nno learned samples: CER {totals['none']:.3f}   leave-one-out: CER {totals['loo']:.3f}")


if __name__ == "__main__":
    main()
