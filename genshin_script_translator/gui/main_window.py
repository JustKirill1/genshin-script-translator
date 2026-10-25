"""Main window."""
from __future__ import annotations

import datetime as _dt
import html
import os

import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QFont, QGuiApplication, QImage, QKeySequence, QPixmap, QCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget, QTextEdit, QToolBar,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, REPO_URL, __version__, paths
from ..alphabets import imread_unicode, imwrite_unicode
from ..features import NOISE
from ..history import History
from ..i18n import tr
from ..library import Library
from ..recognizer import TRANSFORMS, Engine, Result, Settings
from ..render import render_annotated
from ..selection import Selection
from ..settings import AppSettings
from .dialogs import (AcceptDialog, ExportLibraryDialog, ImportLibraryDialog, SettingsDialog, alphabet_title,
                      char_title)
from .history_panel import HistoryDock
from .image_view import ImageView
from .library_window import LibraryWindow
from .manual_window import ManualWindow
from .qt_utils import bgr_to_qimage, qimage_to_bgr

IMAGE_FILTER_KEY = "dialog.image_filter"


class RecognizeThread(QThread):
    done = Signal(object, object)          # Result | None, Exception | None

    def __init__(self, engine: Engine, crop: np.ndarray, settings: Settings, offset, region):
        super().__init__()
        self.engine, self.crop, self.settings, self.offset, self.region = engine, crop, settings, offset, region

    def run(self):
        try:
            self.done.emit(self.engine.recognize(self.crop, self.settings, offset=self.offset,
                                                 region=self.region), None)
        except Exception as ex:  # noqa: BLE001
            self.done.emit(None, ex)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.app_settings = settings
        self.engine: Engine | None = None
        self.history = History(paths.history_dir(), settings.history_limit)
        self.image: np.ndarray | None = None
        self.result: Result | None = None
        self.color: tuple | None = None
        self._thread: RecognizeThread | None = None
        self._pending = False
        self._history_id: str | None = None      # history entry of the current image + selection
        self._history_key = None
        self._library_window: LibraryWindow | None = None

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1440, 880)
        self.setAcceptDrops(True)

        self.view = ImageView()
        self.view.selectionChanged.connect(self._on_selection)
        self.view.glyphClicked.connect(self._on_glyph_clicked)
        self.view.colorPicked.connect(self._on_color_picked)

        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(self._build_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([1040, 400])
        self.setCentralWidget(splitter)

        self.history_dock = HistoryDock(self.history, self)
        self.history_dock.entryActivated.connect(self.open_history_entry)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.history_dock)
        self.history_dock.hide()

        self._build_actions()
        self._hint = tr("status.hint")
        self.statusBar().showMessage(tr("status.loading"))
        QApplication.clipboard().dataChanged.connect(self._on_clipboard)
        QTimer.singleShot(30, self._load_engine)

    # ------------------------------------------------------------------ actions, menus, toolbar
    def _act(self, key: str, slot, shortcut: str | None = None, checkable: bool = False) -> QAction:
        a = QAction(tr(key), self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        self.a_open = self._act("action.open", self.open_file, "Ctrl+O")
        self.a_paste = self._act("action.paste", self.paste, "Ctrl+V")
        self.a_capture = self._act("action.screenshot", self.capture_screen, "F9")
        self.a_export_img = self._act("action.export_image", self.export_image, "Ctrl+E")
        self.a_quit = self._act("action.quit", self.close, "Ctrl+Q")
        self.a_recognize = self._act("action.recognize", self.recognize, "F5")
        self.a_accept = self._act("action.accept_remaining", self.accept_remaining, "Ctrl+Return")
        self.a_clear_sel = self._act("action.clear_selection", self.view.clear_selection, "Esc")
        self.a_fit = self._act("action.fit", self.view.fit, "Ctrl+0")
        self.a_rect = self._act("action.tool_rect", lambda: self._set_tool(ImageView.TOOL_RECT), "R", True)
        self.a_lasso = self._act("action.tool_lasso", lambda: self._set_tool(ImageView.TOOL_LASSO), "L", True)
        self.a_eraser = self._act("action.eraser", self._toggle_eraser, "E", True)
        self.a_eraser.setToolTip(tr("action.eraser_tip"))
        self.a_rect.setChecked(True)
        group = QActionGroup(self)
        group.addAction(self.a_rect)
        group.addAction(self.a_lasso)
        self.a_library = self._act("action.library", self.show_library, "Ctrl+L")
        self.a_manual = self._act("action.manual", self.show_manual, "Ctrl+M")
        self.a_manual.setToolTip(tr("panel.manual_tip"))
        self.a_import_lib = self._act("action.import_library", self.import_library)
        self.a_export_lib = self._act("action.export_library", self.export_library)
        self.a_history = self.history_dock.toggleViewAction()
        self.a_history.setText(tr("action.history"))
        self.a_history.setShortcut(QKeySequence("Ctrl+H"))
        self.a_settings = self._act("action.settings", self.show_settings, "Ctrl+,")
        self.a_about = self._act("action.about", self.show_about)
        self.a_repo = self._act("action.project_page", lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))

        mb = self.menuBar()
        m = mb.addMenu(tr("menu.file"))
        for a in (self.a_open, self.a_paste, self.a_capture, None, self.a_export_img, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.edit"))
        for a in (self.a_recognize, self.a_accept, None, self.a_rect, self.a_lasso, self.a_eraser, self.a_clear_sel):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.tools"))
        for a in (self.a_manual, None, self.a_library, self.a_import_lib, self.a_export_lib, None, self.a_history,
                  None, self.a_settings):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.help"))
        m.addAction(self.a_repo)
        m.addAction(self.a_about)

        tb = QToolBar(tr("menu.toolbar"))
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        self.addToolBar(tb)
        for a in (self.a_open, self.a_paste, self.a_capture, None, self.a_recognize, None,
                  self.a_rect, self.a_lasso, self.a_eraser, self.a_clear_sel, self.a_fit, None,
                  self.a_manual, self.a_library, self.a_history, self.a_export_img, self.a_settings):
            tb.addSeparator() if a is None else tb.addAction(a)

    def _build_panel(self) -> QWidget:
        s = self.app_settings
        panel = QWidget()
        panel.setMinimumWidth(370)
        lay = QVBoxLayout(panel)

        box = QGroupBox(tr("panel.options"))
        form = QFormLayout(box)
        self.cb_alpha = QComboBox()
        self.cb_alpha.addItem(tr("option.auto_detect"), "auto")
        form.addRow(tr("panel.alphabet"), self.cb_alpha)

        self.cb_orient = QComboBox()
        for key in ("auto", "h", "v_rtl", "v_ltr"):
            self.cb_orient.addItem(tr(f"orientation.{key}"), key)
        form.addRow(tr("panel.direction"), self.cb_orient)

        self.cb_bin = QComboBox()
        for key in ("auto", "otsu", "flat", "adaptive", "color"):
            self.cb_bin.addItem(tr(f"binarize.{key}"), key)
        form.addRow(tr("panel.binarize"), self.cb_bin)

        self.cb_tf = QComboBox()
        for key in ("auto",) + TRANSFORMS:
            self.cb_tf.addItem(tr(f"transform.{key}"), key)
        form.addRow(tr("panel.transform"), self.cb_tf)

        self.cb_pol = QComboBox()
        for key in ("auto", "light", "dark"):
            self.cb_pol.addItem(tr(f"polarity.{key}"), key)
        form.addRow(tr("panel.polarity"), self.cb_pol)

        prow = QHBoxLayout()
        self.btn_pip = QPushButton(tr("panel.pipette"))
        self.btn_pip.setCheckable(True)
        self.btn_pip.toggled.connect(self._on_pipette)
        self.lbl_color = QLabel()
        self.lbl_color.setFixedSize(26, 22)
        self.lbl_color.setStyleSheet("border:1px solid #555; background:#222;")
        self.sp_tol = QSpinBox()
        self.sp_tol.setRange(5, 150)
        self.sp_tol.setValue(45)
        self.sp_tol.setPrefix(tr("panel.tolerance") + " ")
        prow.addWidget(self.btn_pip)
        prow.addWidget(self.lbl_color)
        prow.addWidget(self.sp_tol, 1)
        form.addRow(tr("panel.text_color"), prow)

        self.sp_space = QDoubleSpinBox()
        self.sp_space.setRange(0.0, 3.0)
        self.sp_space.setSingleStep(0.05)
        self.sp_space.setSpecialValueText(tr("option.auto"))
        self.sp_space.setToolTip(tr("panel.space_tip"))
        form.addRow(tr("panel.space"), self.sp_space)

        self.chk_dict = QCheckBox(tr("panel.dictionary"))
        self.chk_dict.setChecked(s.use_dictionary)
        self.chk_mask = QCheckBox(tr("panel.show_mask"))
        self.chk_clip = QCheckBox(tr("panel.clipboard"))
        self.chk_clip.setChecked(s.watch_clipboard)
        self.chk_clip.setToolTip(tr("panel.clipboard_tip"))
        self.chk_learn = QCheckBox(tr("panel.learn"))
        self.chk_learn.setChecked(s.learn_on_correct)
        self.chk_learn.setToolTip(tr("panel.learn_tip"))
        for w in (self.chk_dict, self.chk_mask, self.chk_clip, self.chk_learn):
            form.addRow(w)
        lay.addWidget(box)

        self.btn_run = QPushButton(tr("panel.recognize"))
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.recognize)
        run_row = QHBoxLayout()
        run_row.addWidget(self.btn_run, 1)
        self.btn_manual = QPushButton(tr("panel.manual"))
        self.btn_manual.setMinimumHeight(38)
        self.btn_manual.setToolTip(tr("panel.manual_tip"))
        self.btn_manual.clicked.connect(self.show_manual)
        run_row.addWidget(self.btn_manual)
        lay.addLayout(run_row)

        self.lbl_info = QLabel("—")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.lbl_info)

        self.tabs = QTabWidget()
        res = QWidget()
        rl = QVBoxLayout(res)
        rl.setContentsMargins(4, 6, 4, 4)
        self.lbl_text = QLabel(tr("panel.text"))
        rl.addWidget(self.lbl_text)
        self.txt_main = QTextEdit()
        self.txt_main.setReadOnly(True)
        self.txt_main.setFont(QFont("Segoe UI", 13))
        rl.addWidget(self.txt_main, 3)
        rl.addWidget(QLabel(tr("panel.raw")))
        self.txt_raw = QTextEdit()
        self.txt_raw.setReadOnly(True)
        self.txt_raw.setFont(QFont("Consolas", 11))
        rl.addWidget(self.txt_raw, 2)
        brow = QHBoxLayout()
        b1 = QPushButton(tr("panel.copy"))
        b1.clicked.connect(lambda: self._copy(self.txt_main.toPlainText()))
        self.btn_accept = QPushButton(tr("action.accept_remaining"))
        self.btn_accept.setToolTip(tr("panel.accept_tip"))
        self.btn_accept.clicked.connect(self.accept_remaining)
        brow.addWidget(b1)
        brow.addWidget(self.btn_accept)
        rl.addLayout(brow)
        self.tabs.addTab(res, tr("panel.tab_result"))

        self.sheet_label = QLabel(tr("panel.no_alphabet"))
        self.sheet_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.sheet_label)
        self.tabs.addTab(sa, tr("panel.tab_chart"))
        lay.addWidget(self.tabs, 1)

        for w in (self.cb_alpha, self.cb_orient, self.cb_bin, self.cb_pol, self.cb_tf):
            w.currentIndexChanged.connect(self._settings_changed)
        self.sp_tol.valueChanged.connect(self._settings_changed)
        self.sp_space.valueChanged.connect(self._settings_changed)
        self.chk_dict.toggled.connect(self._dict_toggled)
        self.chk_mask.toggled.connect(self._update_mask)
        self.cb_alpha.currentIndexChanged.connect(self._alpha_changed)
        return panel

    # ------------------------------------------------------------------ engine
    def _load_engine(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.engine = Engine(Library(paths.builtin_library_dir(), paths.user_library_dir()))
        except Exception as ex:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("common.error"), tr("error.load_alphabets", error=str(ex)))
            return
        QApplication.restoreOverrideCursor()
        for a in self.engine.alphabets:
            self.cb_alpha.addItem(alphabet_title(a.key, a.title), a.key)
        self.statusBar().showMessage(tr("status.loaded", alphabets=len(self.engine.alphabets),
                                        words=len(self.engine.lexicon), samples=self.engine.library.count())
                                     + " " + self._hint)

    def settings(self) -> Settings:
        return Settings(alphabet=self.cb_alpha.currentData(), orientation=self.cb_orient.currentData(),
                        binarize=self.cb_bin.currentData(), transform=self.cb_tf.currentData(),
                        polarity=self.cb_pol.currentData(), color=self.color, color_tol=self.sp_tol.value(),
                        space_factor=self.sp_space.value(), use_dictionary=self.chk_dict.isChecked())

    # ------------------------------------------------------------------ loading images
    def set_image(self, bgr: np.ndarray, auto_run: bool = True, selection: Selection | None = None):
        self.image = bgr
        self.result = None
        self._history_id, self._history_key = None, None
        self.view.set_image(bgr, selection)
        self._show_result()
        h, w = bgr.shape[:2]
        if selection is not None and not selection.is_empty():
            self.recognize()
        elif auto_run and w * h <= 1_200_000:
            self.statusBar().showMessage(tr("status.image", w=w, h=h) + " " + self._hint)
            self.recognize()
        else:
            self.statusBar().showMessage(tr("status.image", w=w, h=h) + " " + tr("status.select_area"))

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("dialog.open_title"), "", tr(IMAGE_FILTER_KEY))
        if path:
            self.load_path(path)

    def load_path(self, path: str):
        img = imread_unicode(path)
        if img is None:
            QMessageBox.warning(self, tr("common.error"), tr("error.open_image", path=path))
            return
        self.set_image(img)

    def paste(self):
        cb = QApplication.clipboard()
        md = cb.mimeData()
        if md is not None and md.hasImage():
            img = cb.image()
            if not img.isNull():
                self.set_image(qimage_to_bgr(img))
                return
        if md is not None and md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    self.load_path(u.toLocalFile())
                    return
        self.statusBar().showMessage(tr("status.no_clipboard_image"), 5000)

    def _on_clipboard(self):
        if not self.chk_clip.isChecked():
            return
        md = QApplication.clipboard().mimeData()
        if md is not None and md.hasImage():
            img = QApplication.clipboard().image()
            if not img.isNull():
                self.set_image(qimage_to_bgr(img))
                self.raise_()
                self.activateWindow()

    def capture_screen(self):
        self.hide()
        QTimer.singleShot(400, self._grab)

    def _grab(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        pix = screen.grabWindow(0)
        self.show()
        self.raise_()
        self.activateWindow()
        if pix.isNull():
            QMessageBox.warning(self, tr("action.screenshot"), tr("error.screenshot"))
            return
        self.set_image(qimage_to_bgr(pix.toImage()), auto_run=False)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    self.load_path(u.toLocalFile())
                    return
        if md.hasImage():
            img = QImage(md.imageData())
            if not img.isNull():
                self.set_image(qimage_to_bgr(img))

    # ------------------------------------------------------------------ recognition
    def _crop(self):
        """(crop, offset, region mask or None, box) for the current selection."""
        h, w = self.image.shape[:2]
        box = self.view.crop_box()
        if box is None:
            return self.image, (0, 0), None, (0, 0, w, h)
        x0, y0, x1, y1 = box
        sel = self.view.selection
        region = None if sel.is_plain_rect() else sel.mask(box)
        return self.image[y0:y1, x0:x1].copy(), (x0, y0), region, box

    def recognize(self):
        if self.engine is None or self.image is None:
            return
        if self._thread is not None:
            self._pending = True          # run again when the current recognition finishes
            return
        s = self.settings()
        if s.binarize == "color" and s.color is None:
            self.statusBar().showMessage(tr("status.need_color"), 8000)
            return
        crop, offset, region, _ = self._crop()
        self.btn_run.setEnabled(False)
        self.btn_run.setText(tr("panel.recognizing"))
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self._thread = RecognizeThread(self.engine, crop, s, offset, region)
        self._thread.done.connect(self._on_recognized)
        self._thread.start()

    def _on_recognized(self, result, error):
        th, self._thread = self._thread, None
        if th is not None:
            th.wait()
            th.deleteLater()
        QApplication.restoreOverrideCursor()
        self.btn_run.setEnabled(True)
        self.btn_run.setText(tr("panel.recognize"))
        if self._pending:
            self._pending = False
            self.recognize()
            return
        if error is not None:
            self.result = None
            QMessageBox.warning(self, tr("error.recognition"), str(error))
        else:
            self.result = result
        if self.result is None:
            self.statusBar().showMessage(tr("status.nothing_found"), 8000)
        else:
            self._save_history()
        self._show_result()

    def _settings_changed(self, *_):
        if self.image is not None and self.result is not None:
            self.recognize()

    def _alpha_changed(self, *_):
        key = self.cb_alpha.currentData()
        if self.engine is not None and key != "auto":
            self._show_sheet(self.engine.alphabet(key))

    def _dict_toggled(self, *_):
        if self.result is not None and self.engine is not None:
            self.engine.apply_dictionary(self.result, self.chk_dict.isChecked())
            self._show_result()

    def _on_selection(self):
        if self.image is not None and self.view.crop_box() is not None:
            self.recognize()

    # ------------------------------------------------------------------ history
    def _save_history(self):
        r = self.result
        if r is None or not r.glyphs:
            return
        key = (id(self.image), repr(self.view.selection.to_json()))
        if key == self._history_key and self._history_id:
            self.history.remove(self._history_id)
        _, _, _, box = self._crop()
        e = self.history.add(self.image, r.corrected_text(), r.raw_text(), r.alphabet.key,
                             self.view.selection, box)
        self._history_id, self._history_key = e.id, key
        self.history_dock.refresh()

    def _update_history_text(self):
        if self._history_id and self.result is not None:
            self.history.update(self._history_id, self.result.corrected_text(), self.result.raw_text())
            self.history_dock.refresh()

    def open_history_entry(self, eid: str):
        e = next((x for x in self.history.entries if x.id == eid), None)
        if e is None:
            return
        img = self.history.image(e)
        if img is None:
            QMessageBox.warning(self, tr("history.title"), tr("history.missing"))
            return
        sel = self.history.selection(e)
        self.set_image(img, auto_run=False, selection=sel if not sel.is_empty() else None)
        if sel.is_empty():
            self.recognize()
        self._history_id = e.id
        self._history_key = (id(self.image), repr(self.view.selection.to_json()))

    # ------------------------------------------------------------------ showing the result
    def _show_result(self):
        r = self.result
        self.view.set_overlay(r)
        self._update_mask()
        self.btn_accept.setEnabled(r is not None and any(not g.manual for g in r.glyphs))
        if r is None:
            self.txt_main.clear()
            self.txt_raw.clear()
            self.lbl_info.setText("—")
            return
        a = r.alphabet
        info = (f"<b style='color:#d3bc8e'>{html.escape(alphabet_title(a.key, a.title))}</b> · "
                + html.escape(tr("result.confidence", value=f"{r.quality * 100:.0f}")))
        if r.transform != "none":
            info += " · " + html.escape(tr(f"transform.{r.transform}").lower())
        if self.cb_alpha.currentData() == "auto" and len(r.alternatives) > 1:
            alts = ", ".join(f"{html.escape(alphabet_title(k, k))} {v * 100:.0f}%" for k, v in r.alternatives[1:3])
            info += f"<br><span style='color:#999'>{html.escape(tr('result.alternatives'))}: {alts}</span>"
        note = tr(f"alphabet_note.{a.key}")
        if note != f"alphabet_note.{a.key}":
            info += f"<br><span style='color:#999'>{html.escape(note)}</span>"
        self.lbl_info.setText(info)
        self.lbl_text.setText(tr("panel.text") if a.spec.english else tr("panel.text_romaji"))
        lines_html = []
        for line in r.corrected:
            words = [f"<span style='color:#8fd18f'>{html.escape(t)}</span>" if changed else html.escape(t)
                     for t, changed in line]
            lines_html.append(" ".join(words))
        self.txt_main.setHtml("<br>".join(lines_html))
        self.txt_raw.setPlainText(r.raw_text())
        self._show_sheet(a)

    def _show_sheet(self, alphabet):
        pix = QPixmap.fromImage(bgr_to_qimage(alphabet.sheet))
        self.sheet_label.setPixmap(pix.scaledToWidth(max(260, self.tabs.width() - 40),
                                                     Qt.TransformationMode.SmoothTransformation))

    def _update_mask(self, *_):
        if self.chk_mask.isChecked() and self.result is not None and self.result.mask is not None:
            self.view.set_mask(self.result.mask, self.result.offset)
        else:
            self.view.set_mask(None)

    def _refresh_after_edit(self):
        self.engine.apply_dictionary(self.result, self.chk_dict.isChecked())
        self._show_result()
        self._update_history_text()

    # ------------------------------------------------------------------ manual correction
    def _on_glyph_clicked(self, idx: int, gpos):
        r = self.result
        if r is None or idx >= len(r.glyphs) or self._thread is not None:
            return
        g = r.glyphs[idx]
        menu = QMenu(self)
        menu.addSection(tr("glyph.choose"))
        for ch, sc in g.candidates(r.chars, 8):
            a = menu.addAction(f"{ch}    {sc * 100:.0f}%")
            a.setData(ch)
        menu.addSeparator()
        other = menu.addAction(tr("glyph.other"))
        confirm = menu.addAction(tr("glyph.confirm", char=g.char))
        menu.addSeparator()
        remove = menu.addAction(tr("glyph.remove"))
        remove_noise = menu.addAction(tr("glyph.remove_noise"))
        reset = menu.addAction(tr("glyph.reset")) if g.manual else None
        chosen = menu.exec(gpos)
        if chosen is None:
            return
        if chosen is remove or chosen is remove_noise:
            if chosen is remove_noise:
                n = self.engine.learn(r, [(idx, NOISE)])
                if n:
                    self.statusBar().showMessage(tr("status.learned_noise"), 6000)
            r.remove_glyph(idx)
            self._refresh_after_edit()
            return
        learn = self.chk_learn.isChecked()
        if chosen is other:
            text, ok = QInputDialog.getText(self, tr("glyph.other_title"), tr("glyph.other_prompt"))
            if not ok or not text.strip():
                return
            g.char, g.manual = text.strip()[0].upper(), True
        elif chosen is confirm:
            g.manual, learn = True, True
        elif reset is not None and chosen is reset:
            g.char, g.manual, learn = r.chars[int(np.argmax(g.scores))], False, False
        else:
            g.char, g.manual = chosen.data(), True
        if learn and g.manual and g.char in r.chars:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                if self.engine.learn(r, [(idx, g.char)]):
                    self.statusBar().showMessage(tr("status.learned", char=g.char,
                                                    alphabet=alphabet_title(r.alphabet.key, r.alphabet.title),
                                                    total=self.engine.library.count()), 6000)
            finally:
                QApplication.restoreOverrideCursor()
        self._refresh_after_edit()
        self._refresh_library_window()

    def accept_remaining(self):
        r = self.result
        if r is None or self.engine is None or self._thread is not None:
            return
        items = [(i, g.char, g.confidence, self.engine.glyph_mask(r, i))
                 for i, g in enumerate(r.glyphs) if not g.manual]
        if not items:
            self.statusBar().showMessage(tr("status.nothing_to_accept"), 5000)
            return
        dlg = AcceptDialog(items, self)
        if dlg.exec() != AcceptDialog.DialogCode.Accepted:
            return
        chosen = dlg.checked()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n = self.engine.learn(r, [(i, r.glyphs[i].char) for i in chosen])
        finally:
            QApplication.restoreOverrideCursor()
        for i in chosen:
            r.glyphs[i].manual = True
        self.statusBar().showMessage(tr("status.accepted", n=len(chosen), learned=n,
                                        total=self.engine.library.count()), 6000)
        self._refresh_after_edit()
        self._refresh_library_window()

    # ------------------------------------------------------------------ library
    def show_library(self):
        if self.engine is None:
            return
        if self._library_window is None:
            self._library_window = LibraryWindow(self.engine, self.import_library, self.export_library, self)
            self._library_window.changed.connect(self._library_changed)
        if self.result is not None:
            self._library_window.show_alphabet(self.result.alphabet.key)
        self._library_window.refresh()
        self._library_window.show()
        self._library_window.raise_()

    def _refresh_library_window(self):
        if self._library_window is not None and self._library_window.isVisible():
            self._library_window.refresh()

    def _library_changed(self, *_):
        if self.image is not None and self.result is not None:
            self.recognize()

    def export_library(self):
        if self.engine is None:
            return
        dlg = ExportLibraryDialog(self.engine.library, self.engine.alphabets, self.app_settings.author, self)
        if dlg.exec() != ExportLibraryDialog.DialogCode.Accepted:
            return
        author = dlg.ed_author.text().strip()
        if author and author != self.app_settings.author:
            self.app_settings.author = author
            self.app_settings.save()
        name = f"{author or 'library'}-{_dt.date.today().isoformat()}.gsrlib"
        path, _ = QFileDialog.getSaveFileName(self, tr("export_lib.title"),
                                              os.path.join(os.path.expanduser("~"), name), tr("dialog.gsrlib_filter"))
        if not path:
            return
        if not path.lower().endswith(".gsrlib"):
            path += ".gsrlib"
        n = self.engine.library.export(path, dlg.checks.selected(), dlg.chk_builtin.isChecked(),
                                       dlg.chk_noise.isChecked(), author, __version__)
        QMessageBox.information(self, tr("export_lib.title"), tr("export_lib.done", n=n, path=path))

    def import_library(self):
        if self.engine is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("import_lib.title"), "", tr("dialog.gsrlib_open_filter"))
        if not path:
            return
        try:
            summary = Library.read_manifest(path)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, tr("import_lib.title"), tr("import_lib.bad_file", error=str(ex)))
            return
        dlg = ImportLibraryDialog(summary, self.engine.alphabets, path, self)
        if dlg.exec() != ImportLibraryDialog.DialogCode.Accepted:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            added, skipped = self.engine.library.import_package(path, dlg.chk_noise.isChecked(),
                                                                dlg.checks.selected())
            self.engine.rebuild()
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, tr("import_lib.title"), tr("import_lib.done", added=added, skipped=skipped))
        self._refresh_library_window()
        self._library_changed()

    # ------------------------------------------------------------------ manual mode
    def show_manual(self):
        if self.engine is None:
            return
        crop = None
        if self.image is not None:
            crop, _, _, _ = self._crop()
        if self.result is not None:
            key = self.result.alphabet.key
        elif self.cb_alpha.currentData() != "auto":
            key = self.cb_alpha.currentData()
        else:
            key = self.engine.alphabets[0].key
        text = self.result.raw_text() if self.result is not None else ""
        self._manual_window = ManualWindow(self.engine, crop, key, text, self)
        self._manual_window.show()
        self._manual_window.raise_()

    # ------------------------------------------------------------------ export image, settings, about
    def export_image(self):
        r = self.result
        if r is None or self.image is None:
            self.statusBar().showMessage(tr("status.nothing_to_export"), 5000)
            return
        _, _, _, box = self._crop()
        title = f"{alphabet_title(r.alphabet.key, r.alphabet.title)} - {tr('result.confidence', value=f'{r.quality * 100:.0f}')}"
        img = render_annotated(self.image, r, box if self.view.crop_box() else None, title)
        name = f"{r.alphabet.key}-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(self, tr("action.export_image"),
                                              os.path.join(self.app_settings.resolved_export_dir(), name),
                                              "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if imwrite_unicode(path, img):
            self.statusBar().showMessage(tr("status.exported", path=path), 8000)
        else:
            QMessageBox.warning(self, tr("common.error"), tr("error.save", path=path))

    def show_settings(self):
        dlg = SettingsDialog(self.app_settings, self)
        if dlg.exec() != SettingsDialog.DialogCode.Accepted:
            return
        lang_changed = dlg.apply()
        self.app_settings.save()
        self.history.set_limit(self.app_settings.history_limit)
        self.history_dock.refresh()
        if lang_changed:
            QMessageBox.information(self, tr("settings.title"), tr("settings.restart"))

    def show_about(self):
        QMessageBox.about(self, tr("action.about"), tr("about.text", app=APP_NAME, version=__version__, url=REPO_URL))

    # ------------------------------------------------------------------ colour picker
    def _on_pipette(self, on: bool):
        self.view.pipette = on
        self.view.viewport().setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        if on:
            self.statusBar().showMessage(tr("status.pick_color"))

    def _on_color_picked(self, bgr: tuple):
        self.color = bgr
        b, g, r = bgr
        self.lbl_color.setStyleSheet(f"border:1px solid #555; background: rgb({r},{g},{b});")
        self.btn_pip.setChecked(False)
        self.cb_bin.blockSignals(True)
        self.cb_bin.setCurrentIndex(self.cb_bin.findData("color"))
        self.cb_bin.blockSignals(False)
        self.recognize()

    # ------------------------------------------------------------------ tools
    def _set_tool(self, tool: str):
        self.view.tool = tool

    def _toggle_eraser(self, on: bool):
        self.view.eraser = bool(on)

    def _copy(self, text: str):
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(tr("status.copied"), 3000)

    def closeEvent(self, e):
        if self._thread is not None:
            self._thread.wait(5000)
        super().closeEvent(e)
