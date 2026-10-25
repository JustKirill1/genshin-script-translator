"""Dictionary correction: split a recognized line into English words using glyph scores."""
from __future__ import annotations

import os
import re

import numpy as np

# The frequency list contains lots of junk among short "words" (abbreviations, fragments),
# so two-letter words are whitelisted.
TWO_LETTER = {"AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "HI", "IF", "IN", "IS", "IT",
              "ME", "MY", "NO", "OF", "OH", "OK", "ON", "OR", "SO", "TO", "UP", "US", "WE"}


class Lexicon:
    def __init__(self, sources: list[tuple[str, bool]]):
        """sources: [(path, is_frequency_list)]. Curated lists (game names, user words) come first
        and are trusted as is; the frequency list is filtered."""
        words: dict[str, int] = {}
        rank = 0
        for path, frequency_list in sources:
            if not path or not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    w = re.sub(r"[^A-Z]", "", line.split("#", 1)[0].strip().upper())
                    if not w or w in words:
                        continue
                    if len(w) == 1 and w not in ("A", "I"):
                        continue
                    if frequency_list:
                        if len(w) == 2 and w not in TWO_LETTER:
                            continue
                        if len(w) == 3 and (rank > 6000 or not re.search("[AEIOUY]", w)):
                            continue
                    words[w] = rank
                    rank += 1
        self.words = words
        self.by_len: dict[int, tuple[list[str], np.ndarray, np.ndarray]] = {}
        n = max(len(words), 2)
        groups: dict[int, list[str]] = {}
        for w in words:
            groups.setdefault(len(w), []).append(w)
        for L, ws in groups.items():
            codes = np.array([[ord(c) - 65 for c in w] for w in ws], np.int16)
            # 1 for the most frequent words, ~0 for the rarest
            bonus = np.array([1.0 - np.log(words[w] + 2) / np.log(n + 2) for w in ws], np.float32)
            self.by_len[L] = (ws, codes, bonus)

    def __contains__(self, word: str) -> bool:
        return word.upper() in self.words

    def __len__(self):
        return len(self.words)

    def decode_line(self, words: list[tuple[np.ndarray, str, dict]], chars: list[str],
                    pos_tol: float = 0.12, tol: float = 0.05, lam: float = 0.04, mu: float = 0.03,
                    delta: float = 0.15, beta: float = 0.10, gamma: float = 0.06, single: float = 0.10,
                    max_len: int = 16) -> list[tuple[str, bool]]:
        """Split a line into dictionary words without trusting the detected spaces.

        words: one entry per *visible* word: (scores (L, n_chars), raw text, {position: manual letter}).
        A dictionary word may start inside a visible word (penalty ``beta``) and may swallow the
        neighbouring visible word (penalty ``gamma`` per skipped space). An unknown word is only
        allowed as a whole visible word (``mu`` per letter), so names are not chopped into random
        short words. A word that does not match a visible word *and* changes letters pays
        ``delta`` per change, and a one-letter word (A, I) carved out of a longer visible word pays
        ``single`` — otherwise names like ATOSSA turn into "A TOSS A". Only "doubtful" letters can change: a replacement must score within
        ``pos_tol`` of the best letter. Returns [(text, corrected?)].
        """
        rows, raw_all, starts, letter_ok, bounds = [], [], set(), [], []
        pos = 0
        for scores, raw, locked in words:
            L = scores.shape[0]
            s26 = np.full((L, 26), -1.0, np.float32)
            for ci, ch in enumerate(chars):
                if len(ch) == 1 and "A" <= ch <= "Z":
                    s26[:, ord(ch) - 65] = scores[:, ci]
            for p, ch in (locked or {}).items():
                s26[p, :] = -1.0
                if "A" <= ch <= "Z":
                    s26[p, ord(ch) - 65] = 1.0
            letter_ok.extend(ch.isalpha() and "A" <= ch.upper() <= "Z" for ch in raw)
            rows.append(s26)
            raw_all.append(raw)
            starts.add(pos)
            bounds.append((pos, pos + L, raw))
            pos += L
        N = pos
        if N == 0:
            return []
        S = np.concatenate(rows)
        top = S.max(axis=1)
        arg = S.argmax(axis=1)
        letter_ok = np.array(letter_ok)
        vw_end = {a: (b, raw) for a, b, raw in bounds}

        best = np.full(N + 1, np.inf)
        best[0] = 0.0
        back: list = [None] * (N + 1)
        for j in range(N):
            if not np.isfinite(best[j]):
                continue
            if j in vw_end:                                   # unknown word: whole visible word only
                b, raw = vw_end[j]
                c = best[j] + lam + mu * sum(1 for ch in raw if ch.isalpha())
                if c < best[b]:
                    best[b], back[b] = c, (j, raw, False)
            pen_start = 0.0 if j in starts else beta
            for i in range(j + 1, min(N, j + max_len) + 1):
                if not letter_ok[i - 1]:
                    break
                L = i - j
                if L not in self.by_len:
                    continue
                ws, codes, bonus = self.by_len[L]
                per = S[j:i][np.arange(L)[None, :], codes]
                cost_pos = top[j:i][None, :] - per
                ok = (cost_pos <= pos_tol).all(axis=1)
                if not ok.any():
                    continue
                changes = (codes != arg[j:i][None, :]).sum(axis=1)
                total = cost_pos.sum(axis=1)
                ok &= (changes <= max(1, L // 4)) & (total <= tol * L)
                if not ok.any():
                    continue
                crossed = sum(1 for x in starts if j < x < i)
                aligned = j in starts and (i in starts or i == N) and crossed == 0
                val = 1.5 * total - 0.10 * bonus + (0.0 if aligned else delta * changes + (single if L == 1 else 0.0))
                val = np.where(ok, val, np.inf)
                k = int(np.argmin(val))
                c = best[j] + val[k] + lam + pen_start + gamma * crossed
                if c < best[i]:
                    raw_seg = "".join(chr(65 + a) for a in arg[j:i])
                    best[i], back[i] = c, (j, ws[k], ws[k] != raw_seg or crossed > 0 or j not in starts)
        if not np.isfinite(best[N]):
            return [(raw, False) for raw in raw_all]
        out = []
        i = N
        while i > 0:
            j, text, changed = back[i]
            out.append((text, changed))
            i = j
        out.reverse()
        return out
