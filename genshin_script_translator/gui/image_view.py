"""Zoomable image view with rectangle/lasso selection, eraser, glyph overlay and a colour picker."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView)

from ..selection import ADD, SUB, Selection, Shape
from .qt_utils import GOLD, bgr_to_qimage, confidence_color, mask_to_qimage


def _shape_path(s: Shape) -> QPainterPath:
    p = QPainterPath()
    p.addPolygon(QPolygonF([QPointF(x, y) for x, y in s.points]))
    p.closeSubpath()
    return p


class ImageView(QGraphicsView):
    selectionChanged = Signal()
    glyphClicked = Signal(int, object)          # glyph index, global position (QPoint)
    colorPicked = Signal(tuple)                 # BGR

    TOOL_RECT, TOOL_LASSO = "rect", "lasso"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor(24, 24, 30))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._pix)
        self._mask_item = QGraphicsPixmapItem()
        self._mask_item.setZValue(1)
        self.scene().addItem(self._mask_item)

        pen = QPen(GOLD, 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self._sel_item = QGraphicsPathItem()
        self._sel_item.setPen(pen)
        self._sel_item.setBrush(QColor(211, 188, 142, 34))
        self._sel_item.setZValue(3)
        self.scene().addItem(self._sel_item)
        self._draft = QGraphicsPathItem()
        self._draft.setZValue(5)
        self.scene().addItem(self._draft)

        self._overlay: list = []
        self._img: np.ndarray | None = None
        self._press = None
        self._pan_last = None
        self.selection = Selection()
        self.tool = self.TOOL_RECT
        self.eraser = False             # subtract mode (Alt inverts it while dragging)
        self.pipette = False

    # ------------------------------------------------------------------ data
    def has_image(self) -> bool:
        return self._img is not None

    def set_image(self, bgr: np.ndarray, selection: Selection | None = None):
        self._img = bgr
        self._pix.setPixmap(QPixmap.fromImage(bgr_to_qimage(bgr)))
        self.scene().setSceneRect(QRectF(self._pix.pixmap().rect()))
        self._mask_item.setPixmap(QPixmap())
        self.clear_overlay()
        self.selection = selection.copy() if selection else Selection()
        self._update_selection_item()
        self.fit()

    def fit(self):
        if self._img is not None:
            self.fitInView(self._pix, Qt.AspectRatioMode.KeepAspectRatio)

    def crop_box(self) -> tuple[int, int, int, int] | None:
        if self._img is None or self.selection.is_empty():
            return None
        h, w = self._img.shape[:2]
        return self.selection.bbox(w, h)

    def clear_selection(self):
        self.selection = Selection()
        self._update_selection_item()
        self.selectionChanged.emit()

    def set_mask(self, mask: np.ndarray | None, offset=(0, 0)):
        if mask is None:
            self._mask_item.setPixmap(QPixmap())
            return
        self._mask_item.setPixmap(QPixmap.fromImage(mask_to_qimage(mask)))
        self._mask_item.setPos(*offset)

    def clear_overlay(self):
        for it in self._overlay:
            self.scene().removeItem(it)
        self._overlay = []

    def set_overlay(self, r):
        self.clear_overlay()
        if r is None:
            return
        ox, oy = r.offset
        vertical = r.orientation != "h"
        for i, g in enumerate(r.glyphs):
            col = confidence_color(g.confidence, g.manual)
            box = QGraphicsRectItem(g.x + ox, g.y + oy, g.w, g.h)
            pen = QPen(col, 1.6)
            pen.setCosmetic(True)
            box.setPen(pen)
            box.setBrush(QColor(col.red(), col.green(), col.blue(), 28))
            box.setData(0, i)
            box.setZValue(4)
            box.setCursor(Qt.CursorShape.PointingHandCursor)
            box.setToolTip("  ".join(f"{c} {s * 100:.0f}%" for c, s in g.candidates(r.chars, 4)))
            txt = QGraphicsSimpleTextItem(g.char, box)
            f = QFont("Segoe UI", 10)
            f.setBold(True)
            f.setPixelSize(max(7, int(min(g.h, g.w * 1.4) * 0.55)))
            txt.setFont(f)
            txt.setBrush(col)
            br = txt.boundingRect()
            if vertical:
                tx, ty = g.x + ox + g.w + 3, g.y + oy + (g.h - br.height()) / 2
            else:
                tx, ty = g.x + ox + (g.w - br.width()) / 2, g.y + oy - br.height() - 2
            bg = QGraphicsRectItem(QRectF(tx - 2, ty, br.width() + 4, br.height()), box)
            bg.setBrush(QColor(0, 0, 0, 170))
            bg.setPen(Qt.PenStyle.NoPen)
            txt.setPos(tx, ty)
            txt.setZValue(1)
            bg.setZValue(0)
            self.scene().addItem(box)
            self._overlay.append(box)

    # ------------------------------------------------------------------ selection drawing
    def _update_selection_item(self):
        path = QPainterPath()
        for s in self.selection.shapes:
            if len(s.points) < 3:
                continue
            sp = _shape_path(s)
            path = path.united(sp) if s.op == ADD else path.subtracted(sp)
        self._sel_item.setPath(path)

    def _draft_path(self, points, rect_mode: bool, erase: bool):
        pen = QPen(QColor(240, 90, 80) if erase else GOLD, 1.5, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self._draft.setPen(pen)
        path = QPainterPath()
        if rect_mode and len(points) >= 2:
            path.addRect(QRectF(points[0], points[-1]).normalized())
        elif len(points) >= 2:
            path.addPolygon(QPolygonF(points))
        self._draft.setPath(path)

    # ------------------------------------------------------------------ mouse
    def wheelEvent(self, e):
        if self._img is None:
            return
        f = 1.25 ** (e.angleDelta().y() / 120)
        if 0.02 < self.transform().m11() * f < 40:
            self.scale(f, f)

    def mousePressEvent(self, e):
        if self._img is None:
            return
        if e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_last = e.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() == Qt.MouseButton.LeftButton:
            sp = self.mapToScene(e.position().toPoint())
            if self.pipette:
                self._pick_color(sp)
                return
            alt = bool(e.modifiers() & Qt.KeyboardModifier.AltModifier)
            shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._press = {"view": e.position(), "points": [sp], "erase": self.eraser != alt,
                           "add": shift, "moved": False}

    def mouseMoveEvent(self, e):
        if self._pan_last is not None:
            d = e.position() - self._pan_last
            self._pan_last = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        p = self._press
        if p is None:
            return
        if not p["moved"] and (e.position() - p["view"]).manhattanLength() <= 4:
            return
        p["moved"] = True
        sp = self._clamp(self.mapToScene(e.position().toPoint()))
        if self.tool == self.TOOL_RECT:
            p["points"] = [p["points"][0], sp]
        elif (sp - p["points"][-1]).manhattanLength() * self.transform().m11() >= 2:
            p["points"].append(sp)
        self._draft_path(p["points"], self.tool == self.TOOL_RECT, p["erase"])

    def mouseReleaseEvent(self, e):
        if self._pan_last is not None:
            self._pan_last = None
            self.viewport().setCursor(Qt.CursorShape.CrossCursor if self.pipette else Qt.CursorShape.ArrowCursor)
            return
        p, self._press = self._press, None
        if p is None:
            return
        self._draft.setPath(QPainterPath())
        if not p["moved"]:
            # a click: on a glyph — correction menu; elsewhere — clear the selection
            for it in self.items(e.position().toPoint()):
                while it is not None and it.data(0) is None:
                    it = it.parentItem()
                if it is not None and it.data(0) is not None:
                    self.glyphClicked.emit(int(it.data(0)), e.globalPosition().toPoint())
                    return
            if not self.selection.is_empty() and not p["erase"]:
                self.clear_selection()
            return
        pts = p["points"]
        if self.tool == self.TOOL_RECT:
            a, b = pts[0], pts[-1]
            shape = Shape.rect(a.x(), a.y(), b.x(), b.y(), SUB if p["erase"] else ADD)
        else:
            if len(pts) < 3:
                return
            shape = Shape(SUB if p["erase"] else ADD, [(q.x(), q.y()) for q in pts])
        if shape.op == SUB:
            if self.selection.is_empty():
                return                      # nothing to erase from
            self.selection.shapes.append(shape)
        elif p["add"]:
            self.selection.shapes.append(shape)
        else:
            self.selection = Selection([shape])
        self._update_selection_item()
        self.selectionChanged.emit()

    def _clamp(self, sp: QPointF) -> QPointF:
        r = self.sceneRect()
        return QPointF(min(max(sp.x(), r.left()), r.right()), min(max(sp.y(), r.top()), r.bottom()))

    def _pick_color(self, sp: QPointF):
        x, y = int(sp.x()), int(sp.y())
        h, w = self._img.shape[:2]
        if 0 <= x < w and 0 <= y < h:
            patch = self._img[max(0, y - 1):y + 2, max(0, x - 1):x + 2].reshape(-1, 3)
            b, g, r = np.median(patch, axis=0).astype(int)
            self.colorPicked.emit((int(b), int(g), int(r)))
