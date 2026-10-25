"""Smoke test of the Qt interface (runs offscreen; skipped when PySide6 is not installed)."""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")


def test_main_window_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("GST_USER_DATA", str(tmp_path))
    import cv2
    from PySide6.QtWidgets import QApplication

    from genshin_script_translator.gui.dialogs import (AcceptDialog, ExportLibraryDialog, ImportLibraryDialog,
                                                       SettingsDialog)
    from genshin_script_translator.gui.main_window import MainWindow
    from genshin_script_translator.gui.theme import apply_dark_theme
    from genshin_script_translator.i18n import set_language
    from genshin_script_translator.library import Library
    from genshin_script_translator.selection import Selection, Shape
    from genshin_script_translator.settings import AppSettings

    for lang in ("ru", "en"):
        set_language(lang)
        app = QApplication.instance() or QApplication([])
        apply_dark_theme(app)
        w = MainWindow(AppSettings())
        w._load_engine()
        assert w.engine is not None and w.cb_alpha.count() == 1 + len(w.engine.alphabets)

        img = cv2.imread(os.path.join(ROOT, "tests", "real", "mond2.png"))
        w.set_image(img, auto_run=False)
        # lasso selection around the second line
        w.view.selection = Selection([Shape("add", [(95, 92), (330, 92), (330, 118), (200, 121), (95, 118)])])
        w.view._update_selection_item()
        crop, offset, region, box = w._crop()
        assert region is not None and offset == (95, 92)
        res = w.engine.recognize(crop, w.settings(), offset=offset, region=region)
        w._on_recognized(res, None)
        assert w.result is not None and "SMITH" in w.result.corrected_text()
        assert w.history.entries, "history entry saved"
        w.chk_mask.setChecked(True)
        w._show_result()

        # manual correction path without the popup menu
        g = w.result.glyphs[0]
        g.char, g.manual = "S", True
        w.engine.learn(w.result, [(0, "S")])
        w._refresh_after_edit()
        w.result.remove_glyph(len(w.result.glyphs) - 1)
        w._refresh_after_edit()

        items = [(i, gl.char, gl.confidence, w.engine.glyph_mask(w.result, i)) for i, gl in enumerate(w.result.glyphs)]
        dlg = AcceptDialog(items)
        dlg._uncheck_low()
        assert len(dlg.checked()) <= len(items)

        w.show_library()
        lw = w._library_window
        lw.refresh()
        lw.show_alphabet("common")
        lw.page().list.setCurrentRow(0)
        lw.page()._show_details()

        exp = ExportLibraryDialog(w.engine.library, w.engine.alphabets, "tester")
        path = str(tmp_path / f"t-{lang}.gsrlib")
        n = w.engine.library.export(path, exp.checks.selected(), True, True, "tester")
        assert n > 0
        ImportLibraryDialog(Library.read_manifest(path), w.engine.alphabets, path)

        sd = SettingsDialog(w.app_settings)
        sd.apply()
        w.history_dock.refresh()
        w.open_history_entry(w.history.entries[0].id)      # starts recognition in a worker thread
        if w._thread is not None:
            w._thread.wait(60000)
            QApplication.processEvents()                     # deliver the queued "done" signal
        assert w._thread is None and w.result is not None

        from genshin_script_translator.render import render_annotated
        out = render_annotated(w.image, w.result, None, "test")
        assert out.shape[0] > 50
        w.close()


def test_qimage_roundtrip():
    import numpy as np
    from PySide6.QtWidgets import QApplication

    from genshin_script_translator.gui.qt_utils import bgr_to_qimage, qimage_to_bgr
    QApplication.instance() or QApplication([])
    a = (np.random.default_rng(0).random((37, 53, 3)) * 255).astype(np.uint8)
    assert (qimage_to_bgr(bgr_to_qimage(a)) == a).all()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
