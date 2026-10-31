"""
Server-side Markdown for advisor replies. The input is escaped first and only a fixed set of tags is emitted, so model
output can never inject markup. Supports headings, fenced code, quotes, rules, nested-free lists, GFM tables, and
inline code / bold / italic / strikethrough / safe links (single newlines become line breaks, as the chat expects).
"""

from __future__ import annotations

import re
from html import escape

from markupsafe import Markup

_FENCE = re.compile(r"^```")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_BULLET = re.compile(r"^\s*[*+-]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_STRIKE = re.compile(r"~~(.+?)~~")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_SAFE_HREF = re.compile(r"^(?:https?://|mailto:|/(?!/)|#)", re.IGNORECASE)
_HEADING_LEVEL = {1: "h3", 2: "h3", 3: "h4", 4: "h5", 5: "h6", 6: "h6"}


def _inline(raw: str) -> str:
    """Escapes `raw` then applies inline formatting; code spans are shielded from the other rules."""
    text = escape(raw, quote=True)
    spans: list[str] = []

    def stash(match: re.Match) -> str:
        spans.append(f'<code class="font-mono">{match.group(1)}</code>')
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE.sub(stash, text)

    def link(match: re.Match) -> str:
        label, href = match.group(1), match.group(2)
        if not _SAFE_HREF.match(href):
            return label
        return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{label}</a>'

    text = _LINK.sub(link, text)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = _STRIKE.sub(r"<del>\1</del>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table(lines: list[str]) -> str:
    head, body = _cells(lines[0]), [_cells(row) for row in lines[2:]]
    out = ["<table><thead><tr>", *(f"<th>{_inline(c)}</th>" for c in head), "</tr></thead><tbody>"]
    for row in body:
        out += ["<tr>", *(f"<td>{_inline(c)}</td>" for c in row), "</tr>"]
    return "".join(out + ["</tbody></table>"])


def _is_block_start(line: str, nxt: str | None) -> bool:
    return bool(
        _FENCE.match(line) or _HEADING.match(line) or _RULE.match(line) or _BULLET.match(line)
        or _NUMBERED.match(line) or line.startswith(">")
        or ("|" in line and nxt is not None and _TABLE_SEP.match(nxt))
    )


def render_advisor_markdown(text: str | None) -> Markup:
    """Returns the sanitized HTML for an advisor reply, wrapped in the shared `.hvl-chat-markdown` container."""
    if not text:
        return Markup("")
    lines = str(text).replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if not line.strip():
            i += 1
        elif _FENCE.match(line):
            i += 1
            code: list[str] = []
            while i < len(lines) and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f'<pre><code class="font-mono">{escape(chr(10).join(code), quote=True)}</code></pre>')
        elif (m := _HEADING.match(line)):
            tag = _HEADING_LEVEL[len(m.group(1))]
            out.append(f"<{tag}>{_inline(m.group(2))}</{tag}>")
            i += 1
        elif _RULE.match(line):
            out.append("<hr>")
            i += 1
        elif "|" in line and nxt is not None and _TABLE_SEP.match(nxt):
            start = i
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                i += 1
            out.append(_table(lines[start:i]))
        elif line.startswith(">"):
            quote: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(_inline(lines[i].lstrip(">").strip()))
                i += 1
            out.append(f"<blockquote>{'<br>'.join(quote)}</blockquote>")
        elif _BULLET.match(line) or _NUMBERED.match(line):
            pattern, tag = (_BULLET, "ul") if _BULLET.match(line) else (_NUMBERED, "ol")
            items: list[str] = []
            while i < len(lines) and (m := pattern.match(lines[i])):
                items.append(f"<li>{_inline(m.group(1))}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
        else:
            para: list[str] = []
            while i < len(lines) and lines[i].strip():
                nxt_line = lines[i + 1] if i + 1 < len(lines) else None
                if para and _is_block_start(lines[i], nxt_line):
                    break
                para.append(_inline(lines[i]))
                i += 1
            out.append(f"<p>{'<br>'.join(para)}</p>")
    return Markup(f'<div class="hvl-chat-markdown">{"".join(out)}</div>')
