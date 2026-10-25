"""Synthetic accuracy benchmark over all alphabets (chart glyphs only, no learned samples).

    python tools/benchmark.py
"""
import os
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

from genshin_script_translator.library import Library  # noqa: E402
from genshin_script_translator.recognizer import Engine, Settings  # noqa: E402
from synth import cer, render  # noqa: E402

PHRASES = [
    "THE WIND WILL GUIDE YOU HOME", "WELCOME TO THE CITY OF FREEDOM", "DO NOT ENTER WITHOUT PERMISSION",
    "ADVENTURERS GUILD", "FRESH FISH AND MEAT SOLD HERE", "BEWARE OF THE DRAGON",
    "LIGHT THE LAMPS AT NIGHT", "THE TRAVELER SEEKS HER BROTHER",
]


def main():
    eng = Engine(Library(tempfile.mkdtemp(), tempfile.mkdtemp()))
    rng = np.random.default_rng(1)
    raw_e, dict_e, detected, exact = [], [], [], []
    for alpha in eng.alphabets:
        for k, phrase in enumerate(PHRASES):
            height = int(rng.choice([18, 24, 32, 48]))
            vertical = alpha.key == "inazuma" and k % 2 == 1
            img, truth = render(alpha, phrase, rng, height, vertical=vertical, light=bool(k % 3))
            t = time.time()
            r = eng.recognize(img, Settings())
            raw = r.raw_text() if r else ""
            fixed = r.corrected_text() if r else ""
            raw_e.append(cer(truth, raw))
            dict_e.append(cer(truth, fixed))
            detected.append(bool(r) and r.alphabet.key == alpha.key)
            exact.append(fixed.split() == truth.split())
            print(f"[{alpha.key:8s}] h={height:2d} {'V' if vertical else 'H'} {time.time() - t:4.1f}s "
                  f"cer={raw_e[-1]:.2f}/{dict_e[-1]:.2f} {fixed!r}")
    print(f"\nraw CER {np.mean(raw_e):.3f}  dictionary CER {np.mean(dict_e):.3f}  "
          f"alphabet detected {np.mean(detected) * 100:.0f}%  exact phrases {np.mean(exact) * 100:.0f}%")


if __name__ == "__main__":
    main()
