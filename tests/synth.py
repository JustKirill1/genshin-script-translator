"""Synthetic test images: phrases assembled from chart glyphs, coloured, blurred and JPEG-compressed."""
import cv2
import numpy as np

from genshin_script_translator.features import thickness, warp


def render(alpha, text, rng, height, vertical=False, light=True):
    tpl = {}
    for t in alpha.templates:
        tpl.setdefault(t.char, t)
    med = np.median([t.mask.shape[0] for t in alpha.templates])
    scale = height / med
    stroke = int(rng.choice([-1, 0, 0, 1]))
    angle = rng.uniform(-3, 3)
    pieces, truth = [], []
    for word in text.split():
        w = []
        for ch in word:
            if ch not in tpl:
                continue
            m = warp(tpl[ch].mask, angle, 0, 1.0)
            m = cv2.resize(m, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            m = ((m > 110) * 255).astype(np.uint8)
            m = thickness(m, stroke) if min(m.shape) > 8 else m
            ys, xs = np.nonzero(m)
            w.append(m[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
            truth.append(ch)
        pieces.append(w)
        truth.append(" ")
    truth = "".join(truth).strip()
    gap = max(2, int(height * rng.uniform(0.12, 0.22)))
    space = int(height * rng.uniform(0.6, 0.9))
    if not vertical:
        H = int(height * 1.6)
        total = sum(sum(m.shape[1] for m in w) + gap * (len(w) - 1) for w in pieces) + space * (len(pieces) - 1)
        canvas = np.zeros((H + 2 * height, total + 2 * height), np.uint8)
        x = height
        for w in pieces:
            for m in w:
                y = height + (H - m.shape[0]) // 2
                canvas[y:y + m.shape[0], x:x + m.shape[1]] = np.maximum(canvas[y:y + m.shape[0], x:x + m.shape[1]], m)
                x += m.shape[1] + gap
            x += space - gap
    else:
        W = int(height * 1.8)
        total = sum(sum(m.shape[0] for m in w) + gap * (len(w) - 1) for w in pieces) + space * (len(pieces) - 1)
        canvas = np.zeros((total + 2 * height, W + 2 * height), np.uint8)
        y = height
        for w in pieces:
            for m in w:
                x = height + (W - m.shape[1]) // 2
                canvas[y:y + m.shape[0], x:x + m.shape[1]] = np.maximum(canvas[y:y + m.shape[0], x:x + m.shape[1]], m)
                y += m.shape[0] + gap
            y += space - gap
    h, w = canvas.shape
    noise = cv2.GaussianBlur(rng.normal(0, 1, (h // 8 + 2, w // 8 + 2)).astype(np.float32), (0, 0), 1.5)
    noise = cv2.resize(noise, (w, h))
    if light:
        bg = np.dstack([40 + 12 * noise, 35 + 12 * noise, 30 + 12 * noise])
        fg = np.array([200, 225, 240], np.float32)
    else:
        bg = np.dstack([150 + 15 * noise, 190 + 15 * noise, 215 + 15 * noise])
        fg = np.array([40, 50, 70], np.float32)
    a = cv2.GaussianBlur(canvas.astype(np.float32) / 255, (0, 0), rng.uniform(0.4, 1.0))[:, :, None]
    img = np.clip(bg * (1 - a) + fg * a + rng.normal(0, 4, (h, w, 1)), 0, 255).astype(np.uint8)
    _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(60, 90))])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR), truth


def cer(truth: str, got: str) -> float:
    """Character error rate ignoring spaces."""
    a, b = truth.replace(" ", "").replace("\n", ""), got.replace(" ", "").replace("\n", "")
    d = np.arange(len(b) + 1)
    for i, ca in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (ca != cb))
            prev, d[j] = d[j], cur
    return d[len(b)] / max(1, len(a))
