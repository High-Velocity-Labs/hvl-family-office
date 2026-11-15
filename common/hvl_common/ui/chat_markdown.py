"""
The one server-side renderer for chat Markdown (advisor replies, assistant HUD cards, chat bubbles), exposed to Jinja as
the `chat_markdown` filter. Every character of the input is HTML-escaped before any tag is emitted and only a fixed set
of tags comes out, so model output can never inject markup. A link becomes an anchor only when its target is an http(s)
URL, `mailto:`, a same-site path or a `#` fragment; any other scheme stays plain text.

Supports headings, fenced code, quotes, rules, flat lists, GFM tables (a `|a|b|` run with no `|---|` rule is a body-only
table) and inline code / bold / italic / strikethrough / links; single newlines become line breaks, as chat expects.
The keyword options cover what each app does its own way: heading tags, bare-URL autolinks, a scroll wrapper around
tables, extra attributes on chosen links, and the `.hvl-chat-markdown` container.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any, Callable, Mapping

from markupsafe import Markup

DEFAULT_HEADINGS = ("h1", "h2", "h3", "h4", "h4", "h4")

# Any info string opens a fence (```c#, ```python title=x); only its first word, in class-safe characters, is kept.
_FENCE = re.compile(r"^\s*```\s*([^\s`]*)[^`]*$")
_LANG_UNSAFE = re.compile(r"[^A-Za-z0-9_+-]")
_HEADING = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_BULLET = re.compile(r"^\s*[*+-]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?$")
_PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?![\s*])([^*\n]+?)(?<!\s)\*(?![\w*])")
_STRIKE = re.compile(r"~~([^~\n]+)~~")
_LINK = re.compile(r"\[([^\[\]\n]+)\]\(([^)\[\]\s]+)\)")
_BARE_URL = re.compile(r"https?://[^\s\x00]+")
_SPAN = re.compile(r"\x00(\d+)\x00")
# Bold is `**` only: `__` would bold the middle of `__init__.py`, which agents write outside backticks.
# The inline rules stop at the next delimiter (`[^*]`, no `.+?`), so pathological input stays linear.
# A path must not start with `//` or `/\`: browsers read both as another host.
_SAFE_HREF = re.compile(r"^(?:https?://|mailto:|/(?![/\\])|#)", re.IGNORECASE)
# The text is escaped before links are found, so an escaped quote or bracket ends a URL rather than joining it.
_ENTITY_STOP = re.compile(r"&(?:lt|gt|quot|#x27);")

LinkAttrs = Callable[[str], "Mapping[str, str] | None"]


class _Inline:
    """Inline formatting for one line. Finished fragments (code, anchors) are stashed behind NUL-delimited indexes so
    the later rules never reach inside them; the input's own NULs are dropped first, so it cannot forge an index."""

    def __init__(self, autolink: bool, link_attrs: LinkAttrs | None) -> None:
        self.autolink = autolink
        self.link_attrs = link_attrs

    def render(self, raw: str) -> str:
        spans: list[str] = []

        def stash(fragment: str) -> str:
            spans.append(fragment)
            return f"\x00{len(spans) - 1}\x00"

        def unstash(text: str) -> str:
            return _SPAN.sub(lambda m: spans[int(m.group(1))], text)

        def md_link(match: re.Match[str]) -> str:
            label, href = unstash(_emphasis(match.group(1))), _stop_at_entity(match.group(2))
            if not _SAFE_HREF.match(href) or "\x00" in href:  # a stashed code span inside the target
                return stash(label)  # finished HTML: the autolink pass must not reach inside it
            return stash(self._anchor(href, label))

        def bare_url(match: re.Match[str]) -> str:
            raw_url = match.group(0)
            url = _stop_at_entity(raw_url)
            opens, closes, end = url.count("("), url.count(")"), len(url)
            while end and (url[end - 1] in ".,;:!?*_" or (url[end - 1] == ")" and closes > opens)):
                closes -= url[end - 1] == ")"
                end -= 1
            url = url[:end]
            if url in ("http://", "https://"):
                return raw_url
            return stash(self._anchor(url, url)) + raw_url[len(url) :]

        text = escape(raw.replace("\x00", ""), quote=True)
        text = _CODE.sub(lambda m: stash(f'<code class="font-mono">{m.group(1)}</code>'), text)
        text = _LINK.sub(md_link, text)
        if self.autolink:
            text = _BARE_URL.sub(bare_url, text)
        return unstash(_emphasis(text))

    def _anchor(self, href: str, label: str) -> str:
        """An anchor for an already escaped, already vetted href: opens in a new tab unless `link_attrs` names other
        attributes for it."""
        extra = self.link_attrs(href) if self.link_attrs else None
        attrs = extra if extra is not None else {"target": "_blank", "rel": "noopener noreferrer"}
        rendered = "".join(f' {name}="{escape(str(value), quote=True)}"' for name, value in attrs.items())
        return f'<a href="{href}"{rendered}>{label}</a>'


def _stop_at_entity(url: str) -> str:
    stop = _ENTITY_STOP.search(url)
    return url[: stop.start()] if stop else url


def _emphasis(text: str) -> str:
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return _STRIKE.sub(r"<del>\1</del>", text)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_table_start(line: str, nxt: str | None) -> bool:
    return bool(("|" in line and nxt is not None and _TABLE_SEP.match(nxt.strip())) or _PIPE_ROW.match(line))


def _is_block_start(line: str, nxt: str | None) -> bool:
    return bool(
        _FENCE.match(line) or _HEADING.match(line) or _RULE.match(line) or _BULLET.match(line)
        or _NUMBERED.match(line) or line.lstrip().startswith(">") or _is_table_start(line, nxt)
    )


def render_chat_markdown(
    text: Any,
    *,
    wrap: bool = True,
    headings: tuple[str, ...] = DEFAULT_HEADINGS,
    autolink: bool = False,
    table_class: str = "",
    link_attrs: LinkAttrs | None = None,
) -> Markup:
    """Returns the sanitized HTML for chat Markdown.

    wrap: put the result in the shared `.hvl-chat-markdown` container (an app whose template brings its own styled
        container passes False).
    headings: the tag for each heading level `#` to `######`.
    autolink: also turn bare http(s) URLs in the text into anchors.
    table_class: when set, each table sits in a `<div>` of this class (a sideways-scrolling wrapper).
    link_attrs: given an anchor's escaped href, the attributes it gets instead of `target="_blank" rel=...`, or None
        to keep those.
    """
    if not text:
        return Markup("")
    inline = _Inline(autolink, link_attrs).render
    lines = str(text).replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if not line.strip():
            i += 1
        elif (fence := _FENCE.match(line)):
            lang = _LANG_UNSAFE.sub("", fence.group(1))
            i += 1
            code: list[str] = []
            while i < len(lines) and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            cls = f"font-mono language-{lang}" if lang else "font-mono"
            out.append(f'<pre><code class="{cls}">{escape(chr(10).join(code), quote=False)}</code></pre>')
        elif (m := _HEADING.match(line)):
            tag = headings[len(m.group(1)) - 1]
            out.append(f"<{tag}>{inline(m.group(2))}</{tag}>")
            i += 1
        elif _RULE.match(line):
            out.append("<hr>")
            i += 1
        elif _is_table_start(line, nxt):
            has_head = nxt is not None and bool(_TABLE_SEP.match(nxt.strip()))
            start = i
            i += 2 if has_head else 1
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                i += 1
            out.append(_table(lines[start:i], has_head, table_class, inline))
        elif line.lstrip().startswith(">"):
            quote: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(inline(lines[i].lstrip().lstrip(">").strip()))
                i += 1
            out.append(f"<blockquote>{'<br>'.join(quote)}</blockquote>")
        elif _BULLET.match(line) or _NUMBERED.match(line):
            pattern, tag = (_BULLET, "ul") if _BULLET.match(line) else (_NUMBERED, "ol")
            items: list[str] = []
            while i < len(lines) and (m := pattern.match(lines[i])) and not _RULE.match(lines[i]):
                items.append(f"<li>{inline(m.group(1))}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
        else:
            para: list[str] = []
            while i < len(lines) and lines[i].strip():
                nxt_line = lines[i + 1] if i + 1 < len(lines) else None
                if para and _is_block_start(lines[i], nxt_line):
                    break
                para.append(inline(lines[i]))
                i += 1
            out.append(f"<p>{'<br>'.join(para)}</p>")
    body = "".join(out)
    return Markup(f'<div class="hvl-chat-markdown">{body}</div>' if wrap else body)


def _table(lines: list[str], has_head: bool, table_class: str, inline: Callable[[str], str]) -> str:
    body_rows = lines[2:] if has_head else lines
    out = ["<table>"]
    if has_head:
        out += ["<thead><tr>", *(f"<th>{inline(c)}</th>" for c in _cells(lines[0])), "</tr></thead>"]
    out.append("<tbody>")
    for row in body_rows:
        out += ["<tr>", *(f"<td>{inline(c)}</td>" for c in _cells(row)), "</tr>"]
    out.append("</tbody></table>")
    html = "".join(out)
    return f'<div class="{escape(table_class, quote=True)}">{html}</div>' if table_class else html


__all__ = ["DEFAULT_HEADINGS", "render_chat_markdown"]
