"""Byte-deterministic single-page PDFs (no library): uncompressed content streams, standard Helvetica fonts, no
CreationDate and no document ID.

Used for the legitimate supplier invoices and for the planted "PDF invoice with hidden instructions" attack, whose
hidden layer is white, 1pt, invisible-render-mode text that a human reader never sees but a text extractor does.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TextRun:
    x: float
    y: float
    text: str
    size: float = 10
    bold: bool = False
    hidden: bool = False  # white, render mode 3 (invisible): extractable, never visible on screen or paper


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(runs: list[TextRun], *, title: str) -> bytes:
    ops: list[str] = []
    for r in runs:
        font = "F2" if r.bold else "F1"
        if r.hidden:
            ops.append(f"BT 1 1 1 rg 3 Tr /{font} {r.size:g} Tf {r.x:g} {r.y:g} Td ({_escape(r.text)}) Tj ET")
        else:
            ops.append(f"BT 0 0 0 rg 0 Tr /{font} {r.size:g} Tf {r.x:g} {r.y:g} Td ({_escape(r.text)}) Tj ET")
    content = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Title (" + _escape(title).encode("latin-1") + b") /Producer (synthetic seed generator) >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
