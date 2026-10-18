"""HTML email bodies to text, separating text a human reader would never see (invariant 2: hidden instructions).

Hidden means inside an element styled display:none, visibility:hidden, font-size 0/1px, opacity 0 or white text,
or inside <script>/<style>/<head>. Both halves stay in quarantine; the hidden half is what the sentinel flags.
"""

import re
from html.parser import HTMLParser

_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*[01](?:\.\d+)?(?:px|pt)?\s*(?:;|$)|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)"
    r"|(?<![-\w])color\s*:\s*(?:#fff(?:fff)?|white|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\))",
    re.I,
)
_VOID = {"br", "img", "hr", "meta", "link", "input", "wbr", "col", "area", "base", "source"}
_SKIP = {"script", "style", "head", "title"}


class _Splitter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[bool] = []
        self.visible: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            if tag == "br":
                self.visible.append("\n")
            return
        style = dict(attrs).get("style") or ""
        is_hidden = (tag in _SKIP or bool(_HIDDEN_STYLE.search(style)) or "hidden" in dict(attrs)
                     or (self.stack[-1] if self.stack else False))
        self.stack.append(is_hidden)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if self.stack:
            self.stack.pop()
        if tag in ("p", "div", "tr", "li"):
            self.visible.append("\n")

    def handle_data(self, data):
        if not data.strip():
            return
        (self.hidden if (self.stack and self.stack[-1]) else self.visible).append(data)


def html_to_text(html: str) -> tuple[str, list[str]]:
    """(visible text, hidden text fragments)."""
    p = _Splitter()
    p.feed(html)
    p.close()
    visible = re.sub(r"[ \t]+", " ", "".join(p.visible))
    return re.sub(r"\n\s*\n+", "\n\n", visible).strip(), [h.strip() for h in p.hidden if h.strip()]
