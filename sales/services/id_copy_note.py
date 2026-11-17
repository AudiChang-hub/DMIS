"""身分證影本每組右側的備註排版（T-208）：移植自身分證排版工具 A4Layout.LayoutNote。

自動縮字：16 pt 起每次縮 0.05 mm、最小 12 pt，直到放得進備註區；在空白與中日韓文字之間換行（含禁則），
電話等英數字串一行放不下才拆（優先「-」後面，其次第 4 碼後面）；最小字級仍放不下以「…」截斷。
全形英數轉半形。字寬以 reportlab 量（與列印用同一字型），單位一律公釐。
"""
import math
from dataclasses import dataclass
from functools import lru_cache

from reportlab.pdfbase import pdfmetrics

MM_PER_POINT = 25.4 / 72
NOTE_MAX_FONT = 16 * MM_PER_POINT  # ≈ 5.644 mm
NOTE_MIN_FONT = 12 * MM_PER_POINT  # ≈ 4.233 mm
NOTE_FONT_STEP = 0.05
NOTE_MAX_CHARS = 80

NO_LINE_START = "，。、；：！？）」』》〉】〕｝］…‧·,.;:!?)]}%％ー～"
NO_LINE_END = "（「『《〈【〔｛［([{"
ELLIPSIS = "…"
_NARROW = set("＋－＠．／＃")


@dataclass(frozen=True)
class NoteLayout:
    font_size: float  # mm
    lines: tuple
    line_height: float  # mm
    truncated: bool


def narrow_alphanumerics(text):
    """全形英數與 ＋－＠．／＃ 轉半形（注音輸入法常打出「０９１２－３４５－６７８」）。"""
    out = []
    for ch in text:
        narrow = "０" <= ch <= "９" or "Ａ" <= ch <= "Ｚ" or "ａ" <= ch <= "ｚ" or ch in _NARROW
        out.append(chr(ord(ch) - 0xFEE0) if narrow else ch)
    return "".join(out)


def _is_cjk(ch):
    cp = ord(ch)
    if 0xFF10 <= cp <= 0xFF19 or 0xFF21 <= cp <= 0xFF3A or 0xFF41 <= cp <= 0xFF5A or cp == 0xFF0D:
        return False
    return (0x1100 <= cp <= 0x11FF or 0x2E80 <= cp <= 0x9FFF or 0xA960 <= cp <= 0xA97F or 0xAC00 <= cp <= 0xD7AF
            or 0xF900 <= cp <= 0xFAFF or 0xFE30 <= cp <= 0xFE4F or 0xFF01 <= cp <= 0xFFEF or 0x20000 <= cp <= 0x3FFFF)


def _can_break_between(a, b):
    return (_is_cjk(a) or _is_cjk(b)) and b not in NO_LINE_START and a not in NO_LINE_END


def tokenize(paragraph):
    """切成不可再分的片段：空白（" "）、單一中日韓字（含黏住的標點）、連續的英數字串。"""
    tokens, current, prev = [], "", None
    for ch in paragraph:
        if ch.isspace():
            if current:
                tokens.append(current)
                current = ""
            if tokens and tokens[-1] != " ":
                tokens.append(" ")
            prev = None
            continue
        if prev is not None and _can_break_between(prev, ch) and current:
            tokens.append(current)
            current = ""
        current += ch
        prev = ch
    if current:
        tokens.append(current)
    if tokens and tokens[-1] == " ":
        tokens.pop()
    return tokens


class _Measure:
    def __init__(self, font_name, size_mm):
        self.font_name = font_name
        self.size_pt = size_mm / MM_PER_POINT

    def width(self, text):
        return pdfmetrics.stringWidth(text, self.font_name, self.size_pt) * MM_PER_POINT if text else 0.0


def line_height(font_name, size_mm):
    """字型行距比限制在 1.15–1.35 倍（同工具）。"""
    face = getattr(pdfmetrics.getFont(font_name), "face", None)
    ratio = (face.ascent - face.descent) / 1000 if face is not None else 1.2
    return size_mm * min(max(ratio, 1.15), 1.35)


def _split_token(token, measure, max_width):
    """電話等英數字串拆成每段都放得下的幾段；拆不開回傳 None。選行數最少、斷點較好、第一刀越前面的拆法。"""
    n = len(token)
    penalty = [-1] * (n + 1)
    for p in range(1, n):
        a, b = token[p - 1], token[p]
        if a == "-":
            penalty[p] = 0
        elif a.isascii() and a.isdigit() and b.isascii() and b.isdigit():
            start = p - 1
            while start > 0 and token[start - 1].isascii() and token[start - 1].isdigit():
                start -= 1
            penalty[p] = 1 if p - start == 4 else 2
    best = [None] * (n + 1)
    for s in range(n - 1, -1, -1):
        if s > 0 and penalty[s] < 0:
            continue
        if measure.width(token[s:]) <= max_width:
            best[s] = (1, 0, n)
            continue
        for c in range(s + 1, n):
            if penalty[c] < 0 or best[c] is None:
                continue
            if measure.width(token[s:c]) > max_width:
                break
            rest = best[c]
            candidate = (rest[0] + 1, rest[1] + penalty[c], c)
            current = best[s]
            if current is None or candidate[0] < current[0] or (candidate[0] == current[0] and candidate[1] < current[1]):
                best[s] = candidate
    if best[0] is None:
        return None
    pieces, s = [], 0
    while s < n:
        nxt = best[s][2]
        pieces.append(token[s:nxt])
        s = nxt
    return pieces


def _with_ellipsis(text, measure, max_width, always):
    if not always and measure.width(text) <= max_width:
        return text
    if text.endswith(ELLIPSIS):
        text = text[: -len(ELLIPSIS)]
    chars = list(text)
    while chars and measure.width("".join(chars).rstrip() + ELLIPSIS) > max_width:
        chars.pop()
    return "".join(chars).rstrip() + ELLIPSIS


def _wrap(paragraphs, measure, max_width, force):
    lines = []
    for paragraph in paragraphs:
        line = ""
        start_count = len(lines)
        for token in tokenize(paragraph):
            if token == " ":
                if line:
                    line += " "
                continue
            if measure.width(line + token) <= max_width:
                line += token
                continue
            if line.strip():
                lines.append(line.rstrip())
                line = ""
            if measure.width(token) <= max_width:
                line += token
                continue
            pieces = _split_token(token, measure, max_width)
            if pieces:
                lines.extend(pieces[:-1])
                line += pieces[-1]
            elif not force:
                return None
            else:
                lines.append(_with_ellipsis(token, measure, max_width, always=False))
        last = line.rstrip()
        if last or len(lines) == start_count:
            lines.append(last)  # 空段落保留為空行
    return lines


@lru_cache(maxsize=256)
def layout_note(note, width, height, font_name):
    """備註排版：回傳 NoteLayout（字級、各行、行高皆為公釐）。"""
    text = narrow_alphanumerics((note or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not text:
        return NoteLayout(NOTE_MAX_FONT, (), 0.0, False)
    paragraphs = [paragraph.rstrip() for paragraph in text.split("\n")]
    steps = math.ceil((NOTE_MAX_FONT - NOTE_MIN_FONT) / NOTE_FONT_STEP - 1e-4)
    for index in range(steps + 1):
        size = max(NOTE_MIN_FONT, NOTE_MAX_FONT - index * NOTE_FONT_STEP)
        height_per_line = line_height(font_name, size)
        lines = _wrap(paragraphs, _Measure(font_name, size), width, force=False)
        if lines is not None and len(lines) * height_per_line <= height + 0.01:
            return NoteLayout(size, tuple(lines), height_per_line, False)
    measure = _Measure(font_name, NOTE_MIN_FONT)
    height_per_line = line_height(font_name, NOTE_MIN_FONT)
    lines = _wrap(paragraphs, measure, width, force=True)
    max_lines = max(1, math.floor((height + 0.01) / height_per_line))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _with_ellipsis(lines[-1], measure, width, always=True)
    return NoteLayout(NOTE_MIN_FONT, tuple(lines), height_per_line, True)
