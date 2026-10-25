# PyInstaller spec: one folder with GenshinScriptTranslator.exe and its data.
#   pyinstaller packaging/genshin-script-translator.spec --noconfirm
import os

ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ROOT, "alphabets"), "alphabets"),
        (os.path.join(ROOT, "data"), "data"),
        (os.path.join(ROOT, "genshin_script_translator", "i18n"), os.path.join("genshin_script_translator", "i18n")),
        (os.path.join(ROOT, "genshin_script_translator", "assets"), os.path.join("genshin_script_translator", "assets")),
    ],
    hiddenimports=[],
    excludes=[
        "tkinter", "matplotlib", "scipy", "pandas", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GenshinScriptTranslator",
    console=False,
    icon=os.path.join(ROOT, "packaging", "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GenshinScriptTranslator")
