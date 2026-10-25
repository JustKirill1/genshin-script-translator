"""Window listing learned glyph samples per alphabet: view, relabel, delete, import/export."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import paths
from ..features import NOISE
from ..i18n import tr
from ..library import BUILTIN, IMPORTED, USER, mask_thumbnail
from .dialogs import alphabet_title, char_title
from .qt_utils import gray_icon, gray_to_qimage

SOURCE_NAMES = {BUILTIN: "library.source_builtin", USER: "library.source_user", IMPORTED: "library.source_imported"}


class _AlphabetTab(QWidget):
    def __init__(self, window: "LibraryWindow", alphabet):
        super().__init__()
        self.w, self.alphabet = window, alphabet
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        filters = QHBoxLayout()
        self.cb_char = QComboBox()
        self.cb_source = QComboBox()
        self.cb_source.addItem(tr("library.all_sources"), "")
        for src, key in SOURCE_NAMES.items():
            self.cb_source.addItem(tr(key), src)
        filters.addWidget(QLabel(tr("library.letter")))
        filters.addWidget(self.cb_char, 1)
        filters.addWidget(QLabel(tr("library.source")))
        filters.addWidget(self.cb_source, 1)
        left.addLayout(filters)
        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(QSize(56, 56))
        self.list.setGridSize(QSize(84, 96))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._show_details)
        left.addWidget(self.list, 1)
        lay.addLayout(left, 3)

        right = QVBoxLayout()
        self.big = QLabel()
        self.big.setFixedSize(160, 160)
        self.big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big.setStyleSheet("background:#1e1a18; border:1px solid #3a3b46;")
        self.ref = QLabel()
        self.ref.setFixedSize(160, 120)
        self.ref.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ref.setStyleSheet("background:#1e1a18; border:1px solid #3a3b46;")
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        right.addWidget(QLabel(tr("library.sample")))
        right.addWidget(self.big)
        right.addWidget(QLabel(tr("library.chart_reference")))
        right.addWidget(self.ref)
        right.addWidget(self.info)
        right.addStretch(1)
        lay.addLayout(right, 1)

        self.cb_char.currentIndexChanged.connect(self.refresh_list)
        self.cb_source.currentIndexChanged.connect(self.refresh_list)
        self.refresh()

    def refresh(self):
        keep = self.cb_char.currentData()
        self.cb_char.blockSignals(True)
        self.cb_char.clear()
        self.cb_char.addItem(tr("library.all_letters"), "")
        present = sorted({s.char for s in self.w.library.samples(self.alphabet.key)})
        for ch in sorted(set(self.alphabet.chars) | set(present), key=lambda c: (c == NOISE, c)):
            n = sum(1 for s in self.w.library.samples(self.alphabet.key) if s.char == ch)
            self.cb_char.addItem(f"{char_title(ch)}  ({n})", ch)
        i = self.cb_char.findData(keep)
        self.cb_char.setCurrentIndex(max(0, i))
        self.cb_char.blockSignals(False)
        self.refresh_list()

    def refresh_list(self, *_):
        ch, src = self.cb_char.currentData(), self.cb_source.currentData()
        self.list.clear()
        for s in sorted(self.w.library.samples(self.alphabet.key), key=lambda s: (s.char == NOISE, s.char, s.created)):
            if (ch and s.char != ch) or (src and s.source != src):
                continue
            m = self.w.library.load_mask(s)
            if m is None:
                continue
            it = QListWidgetItem(gray_icon(mask_thumbnail(m, 56)), f"{char_title(s.char)}\n{tr(SOURCE_NAMES[s.source])}")
            it.setData(Qt.ItemDataRole.UserRole, s.id)
            it.setToolTip(self._describe(s))
            self.list.addItem(it)
        self._show_details()

    def _describe(self, s) -> str:
        parts = [f"{char_title(s.char)} — {tr(SOURCE_NAMES[s.source])}"]
        if s.author:
            parts.append(tr("library.author", author=s.author))
        if s.created:
            parts.append(s.created.replace("T", " "))
        return "\n".join(parts)

    def selected_ids(self) -> list[str]:
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems()]

    def _show_details(self):
        ids = self.selected_ids()
        if not ids:
            self.big.clear()
            self.ref.clear()
            self.info.setText(tr("library.select_hint"))
            return
        s = self.w.library.get(ids[0])
        m = self.w.library.load_mask(s) if s else None
        if m is not None:
            self.big.setPixmap(QPixmap.fromImage(gray_to_qimage(mask_thumbnail(m, 150))))
        tpl = next((t for t in self.alphabet.templates if t.char == s.char), None) if s else None
        if tpl is not None:
            self.ref.setPixmap(QPixmap.fromImage(gray_to_qimage(mask_thumbnail(tpl.mask, 110))))
        else:
            self.ref.clear()
        self.info.setText(self._describe(s).replace("\n", "<br>") if s else "")


class LibraryWindow(QDialog):
    changed = Signal(str)                  # alphabet key ("" = several)

    def __init__(self, engine, on_import, on_export, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("library.title"))
        self.resize(900, 600)
        self.engine = engine
        self.library = engine.library
        self._on_import, self._on_export = on_import, on_export
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.pages: list[_AlphabetTab] = []
        for a in engine.alphabets:
            page = _AlphabetTab(self, a)
            self.pages.append(page)
            self.tabs.addTab(page, alphabet_title(a.key, a.title))
        lay.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        b_relabel = QPushButton(tr("library.relabel"))
        b_delete = QPushButton(tr("library.delete"))
        b_restore = QPushButton(tr("library.restore_builtin"))
        b_import = QPushButton(tr("library.import"))
        b_export = QPushButton(tr("library.export"))
        b_folder = QPushButton(tr("settings.open_folder"))
        b_relabel.clicked.connect(self.relabel)
        b_delete.clicked.connect(self.delete)
        b_restore.clicked.connect(self.restore)
        b_import.clicked.connect(lambda: self._on_import())
        b_export.clicked.connect(lambda: self._on_export())
        b_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.user_library_dir())))
        for b in (b_relabel, b_delete, b_restore):
            row.addWidget(b)
        row.addStretch(1)
        for b in (b_import, b_export, b_folder):
            row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def page(self) -> _AlphabetTab:
        return self.pages[self.tabs.currentIndex()]

    def show_alphabet(self, key: str):
        for i, p in enumerate(self.pages):
            if p.alphabet.key == key:
                self.tabs.setCurrentIndex(i)

    def refresh(self):
        lib = self.library
        self.summary.setText(tr("library.summary", total=lib.count(), builtin=lib.count(source=BUILTIN),
                                user=lib.count(source=USER), imported=lib.count(source=IMPORTED)))
        for i, p in enumerate(self.pages):
            p.refresh()
            self.tabs.setTabText(i, f"{alphabet_title(p.alphabet.key, p.alphabet.title)} "
                                    f"({lib.count(p.alphabet.key)})")

    def _changed(self, key: str):
        self.engine.rebuild(key or None)
        self.refresh()
        self.changed.emit(key)

    def relabel(self):
        ids = self.page().selected_ids()
        if not ids:
            return
        cur = self.library.get(ids[0]).char
        text, ok = QInputDialog.getText(self, tr("library.relabel"), tr("library.relabel_prompt"),
                                        QLineEdit.EchoMode.Normal, "" if cur == NOISE else cur)
        if not ok or not text.strip():
            return
        ch = text.strip()[0].upper()
        if ch == "~" or text.strip().lower() in ("noise", "шум"):
            ch = NOISE
        for sid in ids:
            self.library.relabel(sid, ch)
        self._changed(self.page().alphabet.key)

    def delete(self):
        ids = self.page().selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, tr("library.delete"), tr("library.delete_confirm", n=len(ids))) \
                != QMessageBox.StandardButton.Yes:
            return
        for sid in ids:
            self.library.remove(sid)
        self._changed(self.page().alphabet.key)

    def restore(self):
        n = self.library.restore_builtin()
        if n:
            self._changed("")
        QMessageBox.information(self, tr("library.title"), tr("library.restored", n=n))
