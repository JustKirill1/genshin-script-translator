"""Application start-up: settings, language, crash log, theme, main window."""
from __future__ import annotations

import os
import sys
import traceback

from .. import APP_NAME, paths
from ..i18n import set_language, tr
from ..settings import AppSettings


def _install_excepthook():
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(paths.log_path(), "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        if sys.__stderr__:
            sys.__stderr__.write(text)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is not None:
                QMessageBox.critical(None, tr("common.error"), tr("error.crash", error=str(exc), log=paths.log_path()))
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    _install_excepthook()
    settings = AppSettings.load()
    set_language(settings.language)

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    from .theme import apply_dark_theme

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    apply_dark_theme(app)
    w = MainWindow(settings)
    w.show()
    files = [a for a in argv[1:] if os.path.isfile(a)]
    if files:
        QTimer.singleShot(300, lambda: w.load_path(files[0]))
    return app.exec()
