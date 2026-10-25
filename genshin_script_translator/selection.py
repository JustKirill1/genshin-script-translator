"""Free-form selection: rectangles and lasso polygons, added or subtracted (eraser).

The GUI only edits a list of shapes in image coordinates; this module turns them into the
crop box and the pixel mask the recognizer uses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

ADD, SUB = "add", "sub"


@dataclass
class Shape:
    op: str                                   # ADD or SUB
    points: list[tuple[float, float]]         # polygon (a rectangle is 4 points)

    @staticmethod
    def rect(x0, y0, x1, y1, op=ADD) -> "Shape":
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        return Shape(op, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    def bbox(self):
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class Selection:
    shapes: list[Shape] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(s.op == ADD and len(s.points) >= 3 for s in self.shapes)

    def copy(self) -> "Selection":
        return Selection([Shape(s.op, list(s.points)) for s in self.shapes])

    def bbox(self, width: int, height: int) -> tuple[int, int, int, int] | None:
        """Bounding box of the added shapes, clipped to the image; None if nothing is selected."""
        adds = [s.bbox() for s in self.shapes if s.op == ADD and len(s.points) >= 3]
        if not adds:
            return None
        x0 = max(0, int(np.floor(min(b[0] for b in adds))))
        y0 = max(0, int(np.floor(min(b[1] for b in adds))))
        x1 = min(width, int(np.ceil(max(b[2] for b in adds))))
        y1 = min(height, int(np.ceil(max(b[3] for b in adds))))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        return x0, y0, x1, y1

    def is_plain_rect(self) -> bool:
        """A single added rectangle needs no pixel mask."""
        if len(self.shapes) != 1 or self.shapes[0].op != ADD or len(self.shapes[0].points) != 4:
            return False
        (ax, ay), (bx, by), (cx, cy), (dx, dy) = self.shapes[0].points
        return ay == by and bx == cx and cy == dy and dx == ax

    def mask(self, box: tuple[int, int, int, int]) -> np.ndarray:
        """uint8 mask (255 = selected) for the crop ``box`` = (x0, y0, x1, y1)."""
        x0, y0, x1, y1 = box
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        for s in self.shapes:
            if len(s.points) < 3:
                continue
            pts = np.array([[(x - x0), (y - y0)] for x, y in s.points], np.float32)
            pts = np.round(pts).astype(np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(m, [pts], 255 if s.op == ADD else 0)
        return m

    def scaled(self, f: float) -> "Selection":
        return Selection([Shape(s.op, [(x * f, y * f) for x, y in s.points]) for s in self.shapes])

    def to_json(self) -> list:
        return [{"op": s.op, "points": [[round(x, 1), round(y, 1)] for x, y in s.points]} for s in self.shapes]

    @staticmethod
    def from_json(data) -> "Selection":
        return Selection([Shape(d["op"], [tuple(p) for p in d["points"]]) for d in (data or [])])
