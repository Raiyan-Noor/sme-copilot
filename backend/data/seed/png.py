"""Byte-deterministic receipt images: a 5x7 bitmap font rendered into a 1-bit grayscale PNG.

No Pillow and no zlib compression: the image data goes into stored (uncompressed) deflate blocks, so the bytes
don't depend on the Pillow or zlib version. That matters because the extractor's replay cache is keyed on
request content, which includes these images.
"""

import struct
import zlib

_FONT_ROWS = {
    "A": ".###. #...# #...# ##### #...# #...# #...#",
    "B": "####. #...# #...# ####. #...# #...# ####.",
    "C": ".###. #...# #.... #.... #.... #...# .###.",
    "D": "####. #...# #...# #...# #...# #...# ####.",
    "E": "##### #.... #.... ####. #.... #.... #####",
    "F": "##### #.... #.... ####. #.... #.... #....",
    "G": ".###. #...# #.... #.### #...# #...# .####",
    "H": "#...# #...# #...# ##### #...# #...# #...#",
    "I": ".###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.",
    "J": "..### ...#. ...#. ...#. ...#. #..#. .##..",
    "K": "#...# #..#. #.#.. ##... #.#.. #..#. #...#",
    "L": "#.... #.... #.... #.... #.... #.... #####",
    "M": "#...# ##.## #.#.# #.#.# #...# #...# #...#",
    "N": "#...# #...# ##..# #.#.# #..## #...# #...#",
    "O": ".###. #...# #...# #...# #...# #...# .###.",
    "P": "####. #...# #...# ####. #.... #.... #....",
    "Q": ".###. #...# #...# #...# #.#.# #..#. .##.#",
    "R": "####. #...# #...# ####. #.#.. #..#. #...#",
    "S": ".#### #.... #.... .###. ....# ....# ####.",
    "T": "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "U": "#...# #...# #...# #...# #...# #...# .###.",
    "V": "#...# #...# #...# #...# #...# .#.#. ..#..",
    "W": "#...# #...# #...# #.#.# #.#.# #.#.# .#.#.",
    "X": "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
    "Y": "#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..",
    "Z": "##### ....# ...#. ..#.. .#... #.... #####",
    "0": ".###. #...# #..## #.#.# ##..# #...# .###.",
    "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
    "2": ".###. #...# ....# ...#. ..#.. .#... #####",
    "3": "####. ....# ....# .###. ....# ....# ####.",
    "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.",
    "5": "##### #.... ####. ....# ....# #...# .###.",
    "6": "..##. .#... #.... ####. #...# #...# .###.",
    "7": "##### ....# ...#. ..#.. .#... .#... .#...",
    "8": ".###. #...# #...# .###. #...# #...# .###.",
    "9": ".###. #...# #...# .#### ....# ...#. .##..",
    " ": "..... ..... ..... ..... ..... ..... .....",
    ".": "..... ..... ..... ..... ..... .##.. .##..",
    ",": "..... ..... ..... ..... .##.. ..#.. .#...",
    ":": "..... .##.. .##.. ..... .##.. .##.. .....",
    "-": "..... ..... ..... ##### ..... ..... .....",
    "$": "..#.. .#### #.#.. .###. ..#.# ####. ..#..",
    "/": "....# ...#. ...#. ..#.. .#... .#... #....",
    "#": ".#.#. .#.#. ##### .#.#. ##### .#.#. .#.#.",
    "@": ".###. #...# #.### #.#.# #.### #.... .###.",
    "(": "...#. ..#.. .#... .#... .#... ..#.. ...#.",
    ")": ".#... ..#.. ...#. ...#. ...#. ..#.. .#...",
    "%": "##..# ##..# ...#. ..#.. .#... #..## #..##",
    "&": ".##.. #..#. #.#.. .#... #.#.# #..#. .##.#",
    "'": "..#.. ..#.. .#... ..... ..... ..... .....",
    "*": "..... ..#.. #.#.# .###. #.#.# ..#.. .....",
    "=": "..... ..... ##### ..... ##### ..... .....",
    "+": "..... ..#.. ..#.. ##### ..#.. ..#.. .....",
}
FONT = {ch: [row for row in rows.split()] for ch, rows in _FONT_ROWS.items()}
GLYPH_W, GLYPH_H = 5, 7


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _stored_zlib(raw: bytes) -> bytes:
    """zlib stream made of stored deflate blocks (no compression), so output never depends on the zlib build."""
    out = bytearray(b"\x78\x01")
    step = 65535
    for start in range(0, max(len(raw), 1), step):
        block = raw[start:start + step]
        final = 1 if start + step >= len(raw) else 0
        out += bytes([final]) + struct.pack("<HH", len(block), len(block) ^ 0xFFFF) + block
    out += struct.pack(">I", zlib.adler32(raw) & 0xFFFFFFFF)
    return bytes(out)


def render_text_png(lines: list[tuple[str, int]], *, width_chars: int = 34, scale: int = 3,
                    margin: int = 24, line_gap: int = 9) -> bytes:
    """Render (text, x_offset_px) lines as black text on white. Text is uppercased; unknown chars render as space.

    The per-line x offset lets the generator draw a "pasted-in" line slightly out of alignment, the way an edited
    receipt photo often looks.
    """
    char_w = (GLYPH_W + 1) * scale
    line_h = GLYPH_H * scale + line_gap
    width = margin * 2 + width_chars * char_w
    height = margin * 2 + len(lines) * line_h
    pixels = [bytearray(width) for _ in range(height)]  # 1 = ink
    for row, (text, dx) in enumerate(lines):
        y0 = margin + row * line_h
        for col, ch in enumerate(text.upper()[:width_chars]):
            glyph = FONT.get(ch, FONT[" "])
            x0 = margin + dx + col * char_w
            for gy, bits in enumerate(glyph):
                for gx, bit in enumerate(bits):
                    if bit != "#":
                        continue
                    for sy in range(scale):
                        line = pixels[y0 + gy * scale + sy]
                        for sx in range(scale):
                            x = x0 + gx * scale + sx
                            if 0 <= x < width:
                                line[x] = 1
    raw = bytearray()
    for line in pixels:
        raw.append(0)  # filter type: none
        packed = bytearray((width + 7) // 8)
        for x, ink in enumerate(line):
            if not ink:  # grayscale 1-bit: 1 = white
                packed[x >> 3] |= 0x80 >> (x & 7)
        raw += packed
    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", _stored_zlib(bytes(raw))) + \
        _chunk(b"IEND", b"")
