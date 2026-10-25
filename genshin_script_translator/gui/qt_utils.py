"""Conversions between numpy/OpenCV images and Qt images, plus small shared helpers."""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

GOLD = QColor("#d3bc8e")


def qimage_to_bgr(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes())
    arr = buf.reshape(h, bpl)[:, :w * 3].reshape(h, w, 3)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def bgr_to_qimage(a: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(cv2.cvtColor(a, cv2.COLOR_BGR2RGB))
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def gray_to_qimage(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a.astype(np.uint8))
    h, w = a.shape
    return QImage(a.data, w, h, w, QImage.Format.Format_Grayscale8).copy()


def mask_to_qimage(mask: np.ndarray, color=(80, 220, 255), alpha=170) -> QImage:
    h, w = mask.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[mask > 0] = (*color, alpha)
    rgba = np.ascontiguousarray(rgba)
    return QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()


def gray_icon(a: np.ndarray) -> QIcon:
    return QIcon(QPixmap.fromImage(gray_to_qimage(a)))


def confidence_color(c: float, manual: bool = False) -> QColor:
    if manual:
        return QColor(120, 170, 255)
    if c >= 0.80:
        return QColor(90, 220, 120)
    if c >= 0.65:
        return QColor(240, 200, 70)
    return QColor(240, 90, 80)
