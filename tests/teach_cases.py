"""Real screenshots with known text (used by tools/real_eval.py and tools/build_builtin_library.py)."""
import os

import cv2

REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "real")

# (file, crop (x0, y0, x1, y1) or None, alphabet, text lines without spaces)
CASES = [
    ("fontaine2.png", (30, 28, 410, 82), "fontaine", ["FRAGRANCES"]),
    ("fontaine3.png", None, "fontaine", ["THOSEWHODO", "NOTWORK", "SHALLNOTEAT"]),
    ("mond1.png", (70, 80, 280, 130), "common", ["OPEN"]),
    ("mond1.png", (50, 148, 270, 188), "common", ["FINEFOOD"]),
    ("mond2.png", (40, 35, 355, 92), "common", ["SCHULZ"]),
    ("mond2.png", (95, 92, 330, 118), "common", ["SMITHSHOP"]),
]


def load(name, crop):
    img = cv2.imread(os.path.join(REAL, name))
    if crop:
        x0, y0, x1, y1 = crop
        img = img[y0:y1, x0:x1]
    return img
