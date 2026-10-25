"""Command-line recognition.

    python cli.py screenshot.png
    python cli.py screenshot.png --alphabet inazuma --orientation v_rtl --region 100 200 600 260
    python cli.py screenshot.png --export annotated.png
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from genshin_script_translator.alphabets import SPECS, imread_unicode, imwrite_unicode  # noqa: E402
from genshin_script_translator.recognizer import ORIENTATIONS, TRANSFORMS, Engine, Settings  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read Teyvat scripts from a Genshin Impact screenshot")
    ap.add_argument("image")
    ap.add_argument("--alphabet", default="auto", choices=["auto"] + [s.key for s in SPECS])
    ap.add_argument("--orientation", default="auto", choices=("auto",) + ORIENTATIONS)
    ap.add_argument("--transform", default="auto", choices=("auto",) + TRANSFORMS,
                    help="rotation/mirroring of the text (signs seen from behind)")
    ap.add_argument("--region", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--no-dict", action="store_true", help="do not correct words with the dictionary")
    ap.add_argument("--export", metavar="PNG", help="save an annotated image")
    a = ap.parse_args(argv)

    img = imread_unicode(a.image)
    if img is None:
        print(f"Cannot open {a.image}", file=sys.stderr)
        return 2
    x0 = y0 = 0
    crop = img
    if a.region:
        x0, y0, x1, y1 = a.region
        crop = img[y0:y1, x0:x1]
    eng = Engine()
    r = eng.recognize(crop, Settings(alphabet=a.alphabet, orientation=a.orientation, transform=a.transform,
                                     use_dictionary=not a.no_dict), offset=(x0, y0))
    if r is None:
        print("No letters found", file=sys.stderr)
        return 1
    print(f"# {r.alphabet.title}, confidence {r.quality * 100:.0f}%"
          + (f", {r.transform}" if r.transform != "none" else ""))
    print(r.corrected_text())
    if not a.no_dict and r.corrected_text() != r.raw_text():
        print("# letter by letter:")
        print(r.raw_text())
    if a.export:
        from genshin_script_translator.render import render_annotated
        title = f"{r.alphabet.title} - confidence {r.quality * 100:.0f}%"
        imwrite_unicode(a.export, render_annotated(img, r, a.region and tuple(a.region), title))
        print(f"# saved {a.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
