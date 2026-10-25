# Changelog

## 0.2.0 — 2026-10-25

- Manual mode: decode an inscription by clicking glyphs on an on-screen glyph keyboard, with the
  screenshot for reference and live text/dictionary output.
- Inazuma is treated as abbreviated romanized Japanese: the English dictionary is not applied.
- The dictionary keeps foreign words and names whole (no "ME US CAN OR", no "A TOSS A").
- Community glyph library from JustKirill1 in `community/`.

## 0.1.0 — 2026-10-25

First public release.

- Recognition of 7 Teyvat scripts with automatic script, direction, rotation and mirror detection.
- Several binarization strategies (Otsu, background flattening, adaptive, by colour).
- Dictionary line decoder that splits run-together words and corrects doubtful letters.
- Rectangle/lasso selection with an eraser.
- Learning from corrections, "accept remaining letters", noise removal and learned noise.
- Glyph library window, `.gsrlib` export/import for sharing with other players.
- Recognition history, annotated image export, settings, English and Russian interface.
- Command line tool, tests, GitHub Actions CI and Windows release builds.
