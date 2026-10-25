"""Manual mode: pick the glyphs you see from a palette and get the text.

For inscriptions the automatic recognizer cannot read (heavy glow, perspective, tiny text):
the screenshot stays on top for reference, the alphabet's glyphs form an on-screen keyboard,
and the typed glyphs are shown both as script and as Latin letters plus the dictionary result.
"""
from __future__ import annotations

import html

import cv2
import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QPixmap, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSplitter, QTextEdit, QToolButton,
                               QVBoxLayout, QWidget)

from ..i18n import tr
from ..library import mask_thumbnail
from .dialogs import alphabet_title
from .qt_utils import bgr_to_qimage, gray_icon, gray_to_qimage

from ..render import GLYPH_H, render_glyph_text


class ManualWindow(QDialog):
    def __init__(self, engine, image: np.ndarray | None, alphabet_key: str, initial_text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("manual.title"))
        self.resize(1000, 820)
        self.engine = engine
        self.image = image
        self.alphabet = engine.alphabet(alphabet_key)

        lay = QVBoxLayout(self)
        hint = QLabel(tr("manual.hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#aaa;")
        lay.addWidget(hint)
        split = QSplitter(Qt.Orientation.Vertical)
        lay.addWidget(split, 1)

        # --- reference picture
        ref = QWidget()
        rl = QVBoxLayout(ref)
        rl.setContentsMargins(0, 0, 0, 0)
        zrow = QHBoxLayout()
        zrow.addWidget(QLabel(tr("manual.reference")))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(25, 400)
        self.zoom.setValue(100)
        self.zoom.setMaximumWidth(220)
        self.zoom.valueChanged.connect(self._show_reference)
        zrow.addStretch(1)
        zrow.addWidget(QLabel(tr("manual.zoom")))
        zrow.addWidget(self.zoom)
        rl.addLayout(zrow)
        self.ref_label = QLabel(tr("manual.no_image"))
        self.ref_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.ref_label)
        rl.addWidget(sa, 1)
        split.addWidget(ref)

        # --- palette
        pal = QWidget()
        pl = QVBoxLayout(pal)
        pl.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("panel.alphabet")))
        self.cb_alpha = QComboBox()
        for a in engine.alphabets:
            self.cb_alpha.addItem(alphabet_title(a.key, a.title), a.key)
        self.cb_alpha.setCurrentIndex(max(0, self.cb_alpha.findData(alphabet_key)))
        self.cb_alpha.currentIndexChanged.connect(self._alphabet_changed)
        top.addWidget(self.cb_alpha, 1)
        self.chk_letters = QCheckBox(tr("manual.show_letters"))
        self.chk_letters.setChecked(True)
        self.chk_letters.toggled.connect(self._build_palette)
        top.addWidget(self.chk_letters)
        pl.addLayout(top)
        self.palette_box = QWidget()
        self.palette_grid = QGridLayout(self.palette_box)
        self.palette_grid.setSpacing(4)
        psa = QScrollArea()
        psa.setWidgetResizable(True)
        psa.setWidget(self.palette_box)
        pl.addWidget(psa, 1)
        keys = QHBoxLayout()
        for key, slot in (("manual.space", lambda: self._insert(" ")), ("manual.backspace", self._backspace),
                          ("manual.newline", lambda: self._insert("\n")), ("manual.clear", self._clear)):
            b = QPushButton(tr(key))
            b.clicked.connect(slot)
            keys.addWidget(b)
        keys.addStretch(1)
        pl.addLayout(keys)
        split.addWidget(pal)

        # --- composed text and result
        out = QWidget()
        ol = QVBoxLayout(out)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(QLabel(tr("manual.glyphs")))
        self.preview = QLabel()
        self.preview.setMinimumHeight(GLYPH_H + 20)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.preview.setStyleSheet("background:#1e1a18; border:1px solid #3a3b46;")
        prev_sa = QScrollArea()
        prev_sa.setWidgetResizable(True)
        prev_sa.setWidget(self.preview)
        prev_sa.setMinimumHeight(GLYPH_H + 30)
        ol.addWidget(prev_sa, 1)
        row = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(QLabel(tr("manual.latin")))
        self.edit = QPlainTextEdit(initial_text.upper())
        self.edit.setFont(QFont("Consolas", 13))
        self.edit.textChanged.connect(self._update)
        left.addWidget(self.edit)
        self.lbl_result = QLabel(tr("panel.text"))
        right.addWidget(self.lbl_result)
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setFont(QFont("Segoe UI", 13))
        right.addWidget(self.result)
        row.addLayout(left, 1)
        row.addLayout(right, 1)
        ol.addLayout(row, 2)
        brow = QHBoxLayout()
        b_copy = QPushButton(tr("panel.copy"))
        b_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.result.toPlainText()))
        self.chk_dict = QCheckBox(tr("panel.dictionary"))
        self.chk_dict.setChecked(True)
        self.chk_dict.toggled.connect(self._update)
        brow.addWidget(self.chk_dict)
        brow.addStretch(1)
        brow.addWidget(b_copy)
        ol.addLayout(brow)
        split.addWidget(out)
        split.setSizes([300, 260, 260])

        self._build_palette()
        self._show_reference()
        self._update()

    # ------------------------------------------------------------------ palette
    def _alphabet_changed(self, *_):
        self.alphabet = self.engine.alphabet(self.cb_alpha.currentData())
        self._build_palette()
        self._update()

    def _build_palette(self, *_):
        for i in reversed(range(self.palette_grid.count())):
            it = self.palette_grid.takeAt(i)
            if it is not None and it.widget() is not None:
                it.widget().deleteLater()
        show = self.chk_letters.isChecked()
        tpls = sorted(self.alphabet.templates, key=lambda t: (not t.char.isalpha(), t.char))
        cols = 10
        for i, t in enumerate(tpls):
            b = QToolButton()
            b.setIcon(gray_icon(mask_thumbnail(t.mask, 52)))
            b.setIconSize(QSize(52, 52))
            b.setText(t.char if show else "")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon if show
                                 else Qt.ToolButtonStyle.ToolButtonIconOnly)
            b.setToolTip(t.char if show else "")
            b.setMinimumSize(64, 76 if show else 62)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, ch=t.char: self._insert(ch))
            self.palette_grid.addWidget(b, i // cols, i % cols)

    # ------------------------------------------------------------------ editing
    def _insert(self, text: str):
        cur = self.edit.textCursor()
        cur.insertText(text)
        self.edit.setTextCursor(cur)
        self.edit.setFocus()

    def _backspace(self):
        cur = self.edit.textCursor()
        if not cur.hasSelection():
            cur.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        self.edit.setTextCursor(cur)
        self.edit.setFocus()

    def _clear(self):
        self.edit.clear()

    def text(self) -> str:
        return self.edit.toPlainText()

    # ------------------------------------------------------------------ output
    def _update(self, *_):
        raw = self.edit.toPlainText()
        if raw != raw.upper():                     # keep the Latin field in capitals while typing
            cur = self.edit.textCursor()
            pos = cur.position()
            self.edit.blockSignals(True)
            self.edit.setPlainText(raw.upper())
            cur = self.edit.textCursor()
            cur.setPosition(min(pos, len(raw)))
            self.edit.setTextCursor(cur)
            self.edit.blockSignals(False)
            raw = raw.upper()
        img = render_glyph_text(self.alphabet, raw)
        if img is None:
            self.preview.clear()
        else:
            self.preview.setPixmap(QPixmap.fromImage(gray_to_qimage(img)))
        english = self.alphabet.spec.english
        self.lbl_result.setText(tr("panel.text") if english else tr("panel.text_romaji"))
        lines = self.engine.decode_plain(raw, english and self.chk_dict.isChecked())
        self.result.setHtml("<br>".join(
            " ".join(f"<span style='color:#8fd18f'>{html.escape(t)}</span>" if ch else html.escape(t)
                     for t, ch in line) for line in lines))

    def _show_reference(self, *_):
        if self.image is None:
            return
        k = self.zoom.value() / 100.0
        img = self.image
        if k != 1.0:
            img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
        self.ref_label.setPixmap(QPixmap.fromImage(bgr_to_qimage(img)))
