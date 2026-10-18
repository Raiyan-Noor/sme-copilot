"""Text extraction from PDF attachments, with every run marked visible or hidden (invariant 2).

A minimal content-stream reader: it follows the text state operators that decide whether a human can see a run
(fill colour `rg`/`g`/`k`, render mode `Tr`, font size `Tf`) and collects `Tj`/`TJ`/`'`/`"` strings. Streams may be
FlateDecode-compressed. A run is hidden when it uses render mode 3 (invisible), a white fill, or a font smaller
than 2pt. Hidden runs are what a text extractor (or an LLM) reads but the owner never sees on screen or paper, so
the sentinel flags them as `hidden_text`.

This is not a general PDF renderer: it does not resolve fonts' encodings beyond Latin-1 or follow XObjects. A PDF
it cannot read yields no text and `readable=False`, and the extractor then reports low confidence.
"""

import re
import zlib
from dataclasses import dataclass, field

MIN_VISIBLE_PT = 2.0
MAX_STREAM_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class TextRun:
    text: str
    hidden: bool
    reason: str | None = None  # render_mode_3 | white_fill | tiny_font


@dataclass(frozen=True)
class PdfText:
    runs: list[TextRun] = field(default_factory=list)
    readable: bool = True

    @property
    def visible_text(self) -> str:
        return "\n".join(r.text for r in self.runs if not r.hidden)

    @property
    def hidden_runs(self) -> list[TextRun]:
        return [r for r in self.runs if r.hidden]


_STREAM = re.compile(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", re.S)
_TOKEN = re.compile(rb"\((?:\\.|[^\\)])*\)|\[[^\]]*\]|/[^\s/\[\]()<>]+|-?\d*\.?\d+|[A-Za-z'\"*]+|<[0-9A-Fa-f\s]*>")
_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def _unescape(s: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\" and i + 1 < len(s):
            n = s[i + 1:i + 2]
            if n in _ESC:
                out += _ESC[n]
                i += 2
                continue
            m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
            i += 1
            continue
        out += c
        i += 1
    return out.decode("latin-1")


def _strings(token: bytes) -> str:
    if token.startswith(b"("):
        return _unescape(token[1:-1])
    if token.startswith(b"<"):
        try:
            return bytes.fromhex(token[1:-1].decode()).decode("latin-1")
        except ValueError:
            return ""
    if token.startswith(b"["):  # TJ array: strings and kerning numbers
        return "".join(_unescape(m[1:-1]) for m in re.findall(rb"\((?:\\.|[^\\)])*\)", token))
    return ""


def _is_white(op: bytes, nums: list[float]) -> bool:
    if op == b"rg" and len(nums) >= 3:
        return all(v >= 0.95 for v in nums[-3:])
    if op == b"g" and nums:
        return nums[-1] >= 0.95
    if op == b"k" and len(nums) >= 4:
        return all(v <= 0.05 for v in nums[-4:])
    return False


def _runs_from_stream(content: bytes) -> list[TextRun]:
    runs: list[TextRun] = []
    operands: list[bytes] = []
    white = False
    mode = 0
    size = 12.0
    for m in _TOKEN.finditer(content):
        tok = m.group(0)
        if tok[:1] in b"([<" or tok[:1] == b"/" or re.fullmatch(rb"-?\d*\.?\d+", tok):
            operands.append(tok)
            continue
        nums = []
        for o in operands:
            try:
                nums.append(float(o))
            except ValueError:
                pass
        if tok in (b"rg", b"g", b"k"):
            white = _is_white(tok, nums)
        elif tok == b"Tr" and nums:
            mode = int(nums[-1])
        elif tok == b"Tf" and nums:
            size = abs(nums[-1])
        elif tok in (b"Tj", b"TJ", b"'", b'"') and operands:
            text = _strings(operands[-1]).strip()
            if text:
                reason = ("render_mode_3" if mode == 3 else "white_fill" if white
                          else "tiny_font" if size < MIN_VISIBLE_PT else None)
                runs.append(TextRun(text, reason is not None, reason))
        operands = []
    return runs


def extract_pdf_text(data: bytes) -> PdfText:
    if not data.startswith(b"%PDF"):
        return PdfText(readable=False)
    runs: list[TextRun] = []
    for m in _STREAM.finditer(data):
        header, body = m.group(1), m.group(2)
        if len(body) > MAX_STREAM_BYTES or b"/Image" in header or b"/Font" in header and b"/Length1" in header:
            continue
        if b"/FlateDecode" in header:
            try:
                body = zlib.decompress(body)
            except zlib.error:
                continue
        if b"BT" not in body:
            continue
        runs += _runs_from_stream(body)
    return PdfText(runs=runs, readable=bool(runs))
