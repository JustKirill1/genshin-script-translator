"""Dock with recognition history: click an entry to bring back the picture and the selection."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDockWidget, QHBoxLayout, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from ..history import History
from ..i18n import tr
from .dialogs import alphabet_title


class HistoryDock(QDockWidget):
    entryActivated = Signal(str)

    def __init__(self, history: History, parent=None):
        super().__init__(tr("history.title"), parent)
        self.setObjectName("history")
        self.history = history
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        self.list = QListWidget()
        self.list.setIconSize(QSize(64, 40))
        self.list.setWordWrap(True)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(self._activate)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        b = QPushButton(tr("history.clear"))
        b.clicked.connect(self._clear)
        row.addStretch(1)
        row.addWidget(b)
        lay.addLayout(row)
        self.setWidget(w)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for e in self.history.entries:
            text = e.text.replace("\n", " / ")
            if len(text) > 60:
                text = text[:57] + "…"
            it = QListWidgetItem(QIcon(QPixmap(self.history.thumb_path(e))),
                                 f"{text}\n{e.time.replace('T', ' ')} · {alphabet_title(e.alphabet, e.alphabet)}")
            it.setData(Qt.ItemDataRole.UserRole, e.id)
            it.setToolTip(e.text)
            self.list.addItem(it)

    def _activate(self, it: QListWidgetItem):
        self.entryActivated.emit(it.data(Qt.ItemDataRole.UserRole))

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        m = QMenu(self)
        a_open = m.addAction(tr("history.open"))
        a_del = m.addAction(tr("history.delete"))
        chosen = m.exec(self.list.mapToGlobal(pos))
        if chosen is a_open:
            self._activate(it)
        elif chosen is a_del:
            self.history.remove(it.data(Qt.ItemDataRole.UserRole))
            self.refresh()

    def _clear(self):
        if not self.history.entries:
            return
        if QMessageBox.question(self, tr("history.title"), tr("history.clear_confirm")) \
                == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.refresh()
