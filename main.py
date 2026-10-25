"""Genshin Script Translator — desktop app.

    python main.py [screenshot.png]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from genshin_script_translator.gui.app import run
    sys.exit(run())
