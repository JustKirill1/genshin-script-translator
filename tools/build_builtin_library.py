"""Rebuild data/library/builtin from the real screenshots with known text (tests/teach_cases.py).

    python tools/build_builtin_library.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

from genshin_script_translator.library import Library  # noqa: E402
from genshin_script_translator.paths import builtin_library_dir  # noqa: E402
from genshin_script_translator.recognizer import Engine, Settings  # noqa: E402
from teach_cases import CASES, load  # noqa: E402


def main():
    work = Library(tempfile.mkdtemp(), tempfile.mkdtemp())
    eng = Engine(work)
    for name, crop, key, truth in CASES:
        r = eng.recognize(load(name, crop), Settings(alphabet=key, transform="none"))
        lines = [[g for w in line for g in w] for line in r.lines]
        got = ["".join(r.glyphs[g].char for g in ln) for ln in lines]
        if [len(x) for x in got] != [len(t) for t in truth]:
            print(f"skip {name}: {got} vs {truth}")
            continue
        seen = {}
        items = []
        for ln, t in zip(lines, truth):
            for g, ch in zip(ln, t):
                if r.glyphs[g].char != ch or seen.get(ch, 0) < 1:      # every miss + one sample per letter
                    items.append((g, ch))
                    seen[ch] = seen.get(ch, 0) + 1
        print(f"{name}: {got} -> {eng.learn(r, items)} samples")
    out = Library(builtin_library_dir(), tempfile.mkdtemp())
    out.save_builtin_from([(s.alphabet, s.char, work.load_mask(s), s.rel_height) for s in work.samples()])
    print("built-in samples:", out.count())


if __name__ == "__main__":
    main()
