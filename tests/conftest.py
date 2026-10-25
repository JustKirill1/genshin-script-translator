import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# keep test runs away from the real user data folder
os.environ.setdefault("GST_USER_DATA", tempfile.mkdtemp(prefix="gst-test-"))


@pytest.fixture(scope="session")
def engine():
    """Engine with the built-in library and an empty user library."""
    from genshin_script_translator.library import Library
    from genshin_script_translator.paths import builtin_library_dir
    from genshin_script_translator.recognizer import Engine
    return Engine(Library(builtin_library_dir(), tempfile.mkdtemp(prefix="gst-lib-")))


@pytest.fixture(scope="session")
def bare_engine():
    """Engine with chart templates only (no learned samples)."""
    from genshin_script_translator.library import Library
    from genshin_script_translator.recognizer import Engine
    return Engine(Library(tempfile.mkdtemp(prefix="gst-none-"), tempfile.mkdtemp(prefix="gst-lib-")))
