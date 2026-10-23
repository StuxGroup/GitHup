"""Discord component embeds: a custom link preview in each generated page's ``<head>``.

Discord reads ``<script id="discord:component-embed" type="application/json">`` and shows its
components instead of the plain Open Graph card, which stays as the fallback. The block is built
and escaped when the page is generated, so the page itself stays static.
Spec: https://docs.discord.com/developers/link-previews/component-embeds

Rules kept here: one Container (type 17) at the root, no nested Containers, at most 40 components,
link buttons (style 5) with http(s) URLs only, and 3,000 bytes at most. Over the limit, the page
gets an HTML comment instead and Discord falls back to the Open Graph preview.
"""

from __future__ import annotations

import json
import re

MAX_BYTES = 3000

_INLINE = re.compile(r"([\\*_~`|\[\]])")
_LINE_START = re.compile(r"^([#>-])", re.M)


def md(text: str) -> str:
    """Escape Discord markdown so data (names, descriptions) shows as plain text.

    Inline formatting, link brackets and backslashes anywhere; headings, quotes and lists only at
    the start of a line. Each special character gets exactly one backslash in front of it.
    """
    return _LINE_START.sub(r"\\\1", _INLINE.sub(r"\\\1", str(text)))


def text(markdown: str) -> dict:
    return {"type": 10, "content": markdown}


def separator() -> dict:
    return {"type": 14}


def section(markdown: str, thumbnail: str = "") -> dict:
    """Text with the site's icon beside it; plain text when there is no absolute icon URL."""
    if not _is_http(thumbnail):
        return text(markdown)
    return {"type": 9, "components": [text(markdown)], "accessory": {"type": 11, "media": {"url": thumbnail}}}


def buttons(links: list[tuple[str, str]]) -> dict | None:
    """A row of link buttons from ``(label, absolute URL)`` pairs (at most 5); None when none are usable."""
    row = [{"type": 2, "style": 5, "label": label[:80], "url": url} for label, url in links if _is_http(url)][:5]
    return {"type": 1, "components": row} if row else None


def payload(components: list[dict | None], accent: str) -> str | None:
    """The JSON for the block, or None when it would be over Discord's 3,000-byte limit."""
    data = {"component": {"type": 17, "accent_color": int(accent.lstrip("#"), 16),
                          "components": [c for c in components if c]}}
    out = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # "<" as <: data can't close the <script> early (or open a comment in it); JSON decodes it back.
    out = out.replace("<", "\\u003c")
    return None if len(out.encode("utf-8")) > MAX_BYTES else out


def embed(components: list[dict | None], accent: str) -> str:
    """The ``<script>`` block, or an HTML comment when the payload is over the limit."""
    out = payload(components, accent)
    if out is None:
        return f"<!-- discord:component-embed left out: over {MAX_BYTES:,} bytes -->"
    return f'<script id="discord:component-embed" type="application/json">{out}</script>'


def link(label: str, url: str) -> str:
    """``[label](url)`` with the label escaped; just the escaped label without an absolute URL."""
    return f"[{md(label)}]({url})" if _is_http(url) else md(label)


def _is_http(url: str) -> bool:
    return bool(url) and re.match(r"^https?://", url, re.I) is not None and "${" not in url
