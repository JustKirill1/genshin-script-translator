"""Annotated image export: the screenshot area with glyph boxes, letters and the decoded text."""
from __future__ import annotations

import cv2
import numpy as np

from . import APP_NAME

FONT = cv2.FONT_HERSHEY_SIMPLEX
BG = (30, 26, 24)
GOLD = (142, 188, 211)      # BGR of #d3bc8e
GREY = (170, 170, 170)


def confidence_bgr(c: float, manual: bool = False) -> tuple[int, int, int]:
    if manual:
        return (255, 170, 120)
    if c >= 0.80:
        return (120, 220, 90)
    if c >= 0.65:
        return (70, 200, 240)
    return (80, 90, 240)


def _wrap(text: str, scale: float, thick: int, width: int) -> list[str]:
    out = []
    for para in text.split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            cand = (cur + " " + w).strip()
            if cv2.getTextSize(cand, FONT, scale, thick)[0][0] <= width or not cur:
                cur = cand
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return out


def render_annotated(img: np.ndarray, result, box: tuple[int, int, int, int] | None = None,
                     title: str = "", text: str | None = None) -> np.ndarray:
    """img: full BGR image; result: recognizer.Result (glyph boxes relative to result.offset);
    box: area to show (x0, y0, x1, y1) in image coordinates — defaults to the glyphs plus a margin."""
    H, W = img.shape[:2]
    ox, oy = result.offset if result is not None else (0, 0)
    glyphs = result.glyphs if result is not None else []
    if box is None:
        if glyphs:
            x0 = min(g.x for g in glyphs) + ox
            y0 = min(g.y for g in glyphs) + oy
            x1 = max(g.x + g.w for g in glyphs) + ox
            y1 = max(g.y + g.h for g in glyphs) + oy
            m = int(0.6 * max(g.h for g in glyphs))
            box = (max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m))
        else:
            box = (0, 0, W, H)
    x0, y0, x1, y1 = box
    crop = img[y0:y1, x0:x1]
    # scale so the picture is comfortable to look at
    k = float(np.clip(1100.0 / max(1, crop.shape[1]), 1.0, 4.0))
    k = min(k, 1800.0 / max(1, crop.shape[1]))
    view = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
    top_pad = 0
    if glyphs:
        top_pad = int(max(g.h for g in glyphs) * k * 0.6) + 8
    view = cv2.copyMakeBorder(view, top_pad, 0, 0, 0, cv2.BORDER_CONSTANT, value=BG)

    for g in glyphs:
        gx0 = int((g.x + ox - x0) * k)
        gy0 = int((g.y + oy - y0) * k) + top_pad
        gx1 = int((g.x + g.w + ox - x0) * k)
        gy1 = int((g.y + g.h + oy - y0) * k) + top_pad
        col = confidence_bgr(g.confidence, g.manual)
        cv2.rectangle(view, (gx0, gy0), (gx1, gy1), col, max(1, int(k)))
        scale = max(0.45, min(2.2, (gy1 - gy0) / 45.0))
        thick = max(1, int(scale * 2))
        (tw, th), base = cv2.getTextSize(g.char, FONT, scale, thick)
        tx = gx0 + (gx1 - gx0 - tw) // 2
        ty = gy0 - 6
        cv2.rectangle(view, (tx - 3, ty - th - 4), (tx + tw + 3, ty + base - 2), BG, -1)
        cv2.putText(view, g.char, (tx, ty), FONT, scale, col, thick, cv2.LINE_AA)

    # footer with the decoded text
    width = max(view.shape[1], 640)
    if view.shape[1] < width:
        pad = width - view.shape[1]
        view = cv2.copyMakeBorder(view, 0, 0, pad // 2, pad - pad // 2, cv2.BORDER_CONSTANT, value=BG)
    margin = 18
    body = text if text is not None else (result.corrected_text() if result is not None else "")
    t_scale = 1.1 if width >= 900 else 0.8
    lines = _wrap(body, t_scale, 2, width - 2 * margin)
    line_h = int(cv2.getTextSize("Ag", FONT, t_scale, 2)[0][1] * 1.9)
    footer_h = margin + 30 + line_h * max(1, len(lines)) + margin + 18
    footer = np.full((footer_h, width, 3), BG, np.uint8)
    cv2.putText(footer, title, (margin, margin + 16), FONT, 0.6, GOLD, 1, cv2.LINE_AA)
    y = margin + 30 + line_h - 8
    for ln in lines:
        cv2.putText(footer, ln, (margin, y), FONT, t_scale, (235, 235, 235), 2, cv2.LINE_AA)
        y += line_h
    mark = APP_NAME
    (mw, _), _ = cv2.getTextSize(mark, FONT, 0.45, 1)
    cv2.putText(footer, mark, (width - mw - margin, footer_h - 10), FONT, 0.45, GREY, 1, cv2.LINE_AA)
    return np.vstack([view, footer])
