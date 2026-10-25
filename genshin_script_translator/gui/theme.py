"""Dark theme with Genshin-like gold accents."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory


def apply_dark_theme(app: QApplication):
    app.setStyle(QStyleFactory.create("Fusion"))
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(32, 33, 40))
    p.setColor(QPalette.ColorRole.WindowText, QColor(225, 225, 230))
    p.setColor(QPalette.ColorRole.Base, QColor(24, 25, 31))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(38, 39, 47))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(45, 45, 55))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(230, 230, 230))
    p.setColor(QPalette.ColorRole.Text, QColor(230, 230, 235))
    p.setColor(QPalette.ColorRole.Button, QColor(44, 45, 54))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(230, 230, 235))
    p.setColor(QPalette.ColorRole.Highlight, QColor(160, 135, 85))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(20, 20, 20))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(130, 130, 140))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(120, 120, 128))
    app.setPalette(p)
    app.setStyleSheet("""
        QGroupBox { border: 1px solid #3a3b46; border-radius: 6px; margin-top: 10px; padding-top: 6px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #d3bc8e; }
        QPushButton#primary { background: #a88a52; color: #15151a; font-weight: bold;
                              border-radius: 5px; font-size: 14px; }
        QPushButton#primary:hover { background: #c2a468; }
        QPushButton#primary:disabled { background: #5d5340; color: #2a2a2a; }
        QToolBar { spacing: 6px; padding: 3px; border: none; }
        QToolButton:checked { background: #5d5340; border-radius: 4px; }
        QTextEdit, QListWidget { border: 1px solid #3a3b46; border-radius: 4px; }
    """)
