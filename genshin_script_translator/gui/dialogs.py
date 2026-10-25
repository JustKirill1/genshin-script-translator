"""Dialogs: settings, "accept remaining letters", library export and import."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import paths
from ..features import NOISE
from ..i18n import available_languages, tr
from ..library import mask_thumbnail
from ..settings import AppSettings
from .qt_utils import gray_icon


def alphabet_title(key: str, fallback: str = "") -> str:
    t = tr(f"alphabet.{key}")
    return fallback if t == f"alphabet.{key}" and fallback else t


def char_title(char: str) -> str:
    return tr("library.noise") if char == NOISE else char


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(520)
        self.s = settings
        form = QFormLayout()

        self.cb_lang = QComboBox()
        for code, name in available_languages():
            self.cb_lang.addItem(name, code)
        i = self.cb_lang.findData(settings.language)
        self.cb_lang.setCurrentIndex(max(0, i))
        form.addRow(tr("settings.language"), self.cb_lang)

        row = QHBoxLayout()
        self.ed_export = QLineEdit(settings.export_dir)
        self.ed_export.setPlaceholderText(paths.default_export_dir())
        b = QPushButton(tr("common.browse"))
        b.clicked.connect(self._browse)
        row.addWidget(self.ed_export, 1)
        row.addWidget(b)
        form.addRow(tr("settings.export_dir"), row)

        self.ed_author = QLineEdit(settings.author)
        self.ed_author.setPlaceholderText(tr("settings.author_hint"))
        form.addRow(tr("settings.author"), self.ed_author)

        box = QGroupBox(tr("settings.defaults"))
        bl = QVBoxLayout(box)
        self.chk_dict = QCheckBox(tr("panel.dictionary"))
        self.chk_dict.setChecked(settings.use_dictionary)
        self.chk_learn = QCheckBox(tr("panel.learn"))
        self.chk_learn.setChecked(settings.learn_on_correct)
        self.chk_clip = QCheckBox(tr("panel.clipboard"))
        self.chk_clip.setChecked(settings.watch_clipboard)
        for w in (self.chk_dict, self.chk_learn, self.chk_clip):
            bl.addWidget(w)

        self.sp_hist = QSpinBox()
        self.sp_hist.setRange(10, 5000)
        self.sp_hist.setValue(int(settings.history_limit))
        form.addRow(tr("settings.history_limit"), self.sp_hist)

        lib_row = QHBoxLayout()
        lib_path = QLabel(paths.user_data_dir())
        lib_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lib_path.setWordWrap(True)
        ob = QPushButton(tr("settings.open_folder"))
        ob.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.user_data_dir())))
        lib_row.addWidget(lib_path, 1)
        lib_row.addWidget(ob)
        form.addRow(tr("settings.data_folder"), lib_row)
        if paths.is_portable():
            form.addRow("", QLabel(tr("settings.portable")))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(box)
        lay.addWidget(buttons)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("settings.export_dir"),
                                             self.ed_export.text() or paths.default_export_dir())
        if d:
            self.ed_export.setText(d)

    def apply(self) -> bool:
        """Write the values into the settings object. Returns True if the language changed."""
        old_lang = self.s.language
        self.s.language = self.cb_lang.currentData()
        self.s.export_dir = self.ed_export.text().strip()
        self.s.author = self.ed_author.text().strip()
        self.s.use_dictionary = self.chk_dict.isChecked()
        self.s.learn_on_correct = self.chk_learn.isChecked()
        self.s.watch_clipboard = self.chk_clip.isChecked()
        self.s.history_limit = self.sp_hist.value()
        return self.s.language != old_lang


class AcceptDialog(QDialog):
    """List of letters not confirmed yet; the checked ones are learned as correct."""

    def __init__(self, items: list[tuple[int, str, float, object]], parent=None):
        """items: [(glyph index, char, confidence, mask or None)]."""
        super().__init__(parent)
        self.setWindowTitle(tr("accept.title"))
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        info = QLabel(tr("accept.info"))
        info.setWordWrap(True)
        lay.addWidget(info)
        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 48))
        for idx, char, conf, mask in items:
            it = QListWidgetItem(f"{char}    {conf * 100:.0f}%")
            if mask is not None:
                it.setIcon(gray_icon(mask_thumbnail(mask, 48)))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            it.setData(Qt.ItemDataRole.UserRole, idx)
            if conf < 0.65:
                it.setForeground(QBrush(QColor(240, 110, 100)))
                it.setToolTip(tr("accept.low_conf"))
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_all = QPushButton(tr("accept.check_all"))
        b_none = QPushButton(tr("accept.check_none"))
        b_low = QPushButton(tr("accept.uncheck_low"))
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none.clicked.connect(lambda: self._set_all(False))
        b_low.clicked.connect(self._uncheck_low)
        for b in (b_all, b_none, b_low):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self._conf = {idx: conf for idx, _, conf, _ in items}
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("accept.learn"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _set_all(self, on: bool):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _uncheck_low(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if self._conf[it.data(Qt.ItemDataRole.UserRole)] < 0.65:
                it.setCheckState(Qt.CheckState.Unchecked)

    def checked(self) -> list[int]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class _AlphabetChecks(QWidget):
    def __init__(self, alphabets: list[tuple[str, str, int]], parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.boxes: dict[str, QCheckBox] = {}
        for key, title, count in alphabets:
            cb = QCheckBox(f"{title}  ({count})")
            cb.setChecked(count > 0)
            cb.setEnabled(count > 0)
            self.boxes[key] = cb
            lay.addWidget(cb)

    def selected(self) -> list[str]:
        return [k for k, cb in self.boxes.items() if cb.isChecked()]


class ExportLibraryDialog(QDialog):
    def __init__(self, library, alphabets, author: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("export_lib.title"))
        self.library = library
        self._alphabets = alphabets
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("export_lib.info")))
        self.chk_builtin = QCheckBox(tr("export_lib.include_builtin"))
        self.chk_noise = QCheckBox(tr("export_lib.include_noise"))
        self.chk_noise.setChecked(True)
        self.checks_box = QVBoxLayout()
        lay.addLayout(self.checks_box)
        self.checks: _AlphabetChecks | None = None
        lay.addWidget(self.chk_builtin)
        lay.addWidget(self.chk_noise)
        form = QFormLayout()
        self.ed_author = QLineEdit(author)
        self.ed_author.setPlaceholderText(tr("settings.author_hint"))
        form.addRow(tr("settings.author"), self.ed_author)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("export_lib.save"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.chk_builtin.toggled.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_):
        if self.checks is not None:
            self.checks.setParent(None)
        inc = self.chk_builtin.isChecked()
        rows = [(a.key, alphabet_title(a.key, a.title),
                 sum(1 for s in self.library.samples(a.key) if inc or s.source != "builtin"))
                for a in self._alphabets]
        self.checks = _AlphabetChecks(rows)
        self.checks_box.addWidget(self.checks)


class ImportLibraryDialog(QDialog):
    def __init__(self, summary: dict, alphabets, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("import_lib.title"))
        lay = QVBoxLayout(self)
        author = summary.get("author") or tr("import_lib.unknown_author")
        lay.addWidget(QLabel(tr("import_lib.info", file=os.path.basename(path), author=author,
                                total=summary.get("total", 0))))
        per = summary.get("per_alphabet", {})
        titles = {a.key: alphabet_title(a.key, a.title) for a in alphabets}
        self.checks = _AlphabetChecks([(k, titles.get(k, k), n) for k, n in sorted(per.items())])
        lay.addWidget(self.checks)
        self.chk_noise = QCheckBox(tr("import_lib.include_noise", n=summary.get("noise", 0)))
        self.chk_noise.setChecked(True)
        self.chk_noise.setEnabled(summary.get("noise", 0) > 0)
        lay.addWidget(self.chk_noise)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("import_lib.import"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
