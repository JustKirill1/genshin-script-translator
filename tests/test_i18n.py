"""Every UI string used in the code exists in every translation."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "genshin_script_translator")
DYNAMIC = {
    "alphabet": ["common", "inazuma", "sumeru", "deshret", "fontaine", "ancient", "nodkrai"],
    "binarize": ["auto", "otsu", "flat", "adaptive", "color"],
    "orientation": ["auto", "h", "v_rtl", "v_ltr"],
    "polarity": ["auto", "light", "dark"],
    "transform": ["auto", "none", "rot180", "flip_h", "flip_v"],
}
EXTRA = ["library.source_builtin", "library.source_user", "library.source_imported", "dialog.image_filter",
         "alphabet_note.inazuma", "alphabet_note.ancient", "alphabet_note.nodkrai"]


def used_keys() -> set[str]:
    keys = set(EXTRA)
    pat = re.compile(r"""(?:\btr|self\._act)\(\s*["']([a-z_]+\.[a-z_\.]+)["']""")
    for dirpath, _, files in os.walk(PKG):
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    keys |= set(pat.findall(f.read()))
    for prefix, values in DYNAMIC.items():
        keys |= {f"{prefix}.{v}" for v in values}
    return keys


def load(lang):
    with open(os.path.join(PKG, "i18n", f"{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


def test_all_keys_translated():
    keys = used_keys()
    for name in os.listdir(os.path.join(PKG, "i18n")):
        data = load(name[:-5])
        missing = sorted(k for k in keys if k not in data)
        assert not missing, f"{name}: missing {missing}"


def test_translations_have_same_keys_and_placeholders():
    en = load("en")
    ph = re.compile(r"\{(\w+)\}")
    for name in os.listdir(os.path.join(PKG, "i18n")):
        data = load(name[:-5])
        assert set(data) == set(en), f"{name}: keys differ: {sorted(set(data) ^ set(en))}"
        for k, v in en.items():
            assert set(ph.findall(v)) == set(ph.findall(data[k])), f"{name}: placeholders differ in {k}"
