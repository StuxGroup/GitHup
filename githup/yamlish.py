"""A small, strict YAML subset parser.

GitHup reads `.githup.yml` with this parser so the action has no third-party
dependencies. It understands exactly what a GitHup config needs and rejects
everything else with a line number, rather than guessing:

* block mappings (``key: value``) and block sequences (``- item``), nested by
  indentation with spaces (tabs are an error)
* a sequence may sit at the same indentation as its parent key
* scalars: plain, 'single-quoted' and "double-quoted" (with ``\\"``, ``\\\\``,
  ``\\n``, ``\\t`` escapes), integers, floats, ``true``/``false``,
  ``null``/``~``
* flow sequences of scalars on one line (``[200, 301, "400-499"]``) and the
  empty flow mapping ``{}``
* ``#`` comments on their own line or after whitespace

Not supported (a clear error is raised): anchors and aliases, tags, block
scalars (``|`` / ``>``), multiple documents, nested flow collections and
duplicate keys. ``yes``/``no``/``on``/``off`` stay strings, as in YAML 1.2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ["YAMLError", "loads"]


class YAMLError(ValueError):
    """Raised for anything outside the supported subset."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass
class _Line:
    indent: int
    text: str
    no: int


_INT = re.compile(r"^[-+]?\d+$")
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")
_PLAIN_KEY = re.compile(r"^([^\s'\"#\-\[\]{},&*!|>%@`][^:#]*?|-[^\s:#][^:#]*?)\s*:(?:\s+|$)")
_UNSUPPORTED_START = "&*!|>%@`"


def loads(text: str) -> Any:
    """Parse a YAML-subset document and return plain Python values."""
    lines: list[_Line] = []
    for no, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip(" \t"))]:
            raise YAMLError("tabs are not allowed for indentation", no)
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("---", "..."):
            if lines:
                raise YAMLError("multiple documents are not supported", no)
            continue
        lines.append(_Line(len(raw) - len(raw.lstrip(" ")), raw.strip(), no))
    if not lines:
        return None
    if lines[0].indent != 0:
        raise YAMLError("the document must start at column 0", lines[0].no)
    parser = _Parser(lines)
    value = parser.block(0)
    if parser.i < len(lines):
        raise YAMLError("unexpected indentation", lines[parser.i].no)
    return value


def _is_seq_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _split_key(text: str, no: int) -> tuple[str, str] | None:
    """Return (key, rest) when ``text`` is a mapping entry, else None."""
    if text[:1] in ("'", '"'):
        key, rest = _quoted(text, no)
        rest = rest.lstrip(" ")
        if rest.startswith(":") and (len(rest) == 1 or rest[1] == " "):
            return key, rest[1:].strip()
        return None
    m = _PLAIN_KEY.match(text)
    if not m:
        return None
    return m.group(1).strip(), text[m.end():].strip()


class _Parser:
    def __init__(self, lines: list[_Line]):
        self.lines = lines
        self.i = 0

    def block(self, indent: int) -> Any:
        line = self.lines[self.i]
        if _is_seq_item(line.text):
            return self.sequence(indent)
        return self.mapping(indent)

    def _nested(self, parent_indent: int, allow_same_indent_seq: bool) -> Any:
        """Parse the block that follows ``key:`` or a bare ``-``."""
        if self.i >= len(self.lines):
            return None
        nxt = self.lines[self.i]
        if nxt.indent > parent_indent:
            return self.block(nxt.indent)
        if allow_same_indent_seq and nxt.indent == parent_indent and _is_seq_item(nxt.text):
            return self.sequence(parent_indent)
        return None

    def mapping(self, indent: int) -> dict:
        result: dict[str, Any] = {}
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise YAMLError("unexpected indentation", line.no)
            if _is_seq_item(line.text):
                raise YAMLError("a list item cannot appear inside a mapping here", line.no)
            split = _split_key(line.text, line.no)
            if split is None:
                raise YAMLError(f"expected 'key: value', got {line.text!r}", line.no)
            key, rest = split
            if key in result:
                raise YAMLError(f"duplicate key {key!r}", line.no)
            self.i += 1
            if rest == "" or rest.startswith("#"):
                result[key] = self._nested(indent, allow_same_indent_seq=True)
            else:
                result[key] = _scalar(rest, line.no)
        return result

    def sequence(self, indent: int) -> list:
        result: list[Any] = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise YAMLError("unexpected indentation", line.no)
            if not _is_seq_item(line.text):
                break
            rest = line.text[1:].lstrip(" ")
            if rest == "" or rest.startswith("#"):
                self.i += 1
                result.append(self._nested(indent, allow_same_indent_seq=False))
                continue
            item_indent = indent + (len(line.text) - len(rest))
            if _is_seq_item(rest) or _split_key(rest, line.no) is not None:
                # Re-read the rest of this line as the first line of a nested
                # block that starts at the column after "- ".
                self.lines[self.i] = _Line(item_indent, rest, line.no)
                result.append(self.block(item_indent))
            else:
                self.i += 1
                result.append(_scalar(rest, line.no))
        return result


def _quoted(s: str, no: int) -> tuple[str, str]:
    """Parse a quoted scalar at the start of ``s``; return (value, remainder)."""
    q = s[0]
    out: list[str] = []
    i = 1
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "0": "\0", "r": "\r"}
    while i < len(s):
        c = s[i]
        if q == "'" and c == "'":
            if s[i + 1 : i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), s[i + 1 :]
        if q == '"' and c == "\\":
            nxt = s[i + 1 : i + 2]
            if nxt not in escapes:
                raise YAMLError(f"unsupported escape sequence \\{nxt}", no)
            out.append(escapes[nxt])
            i += 2
            continue
        if q == '"' and c == '"':
            return "".join(out), s[i + 1 :]
        out.append(c)
        i += 1
    raise YAMLError("unterminated quoted string", no)


def _only_comment(rest: str, no: int) -> None:
    rest = rest.strip()
    if rest and not rest.startswith("#"):
        raise YAMLError(f"unexpected text after value: {rest!r}", no)


def _scalar(s: str, no: int) -> Any:
    s = s.strip()
    if not s:
        return None
    if s[0] in ("'", '"'):
        value, rest = _quoted(s, no)
        _only_comment(rest, no)
        return value
    if s[0] == "[":
        return _flow_sequence(s, no)
    if s[0] == "{":
        if not re.match(r"^\{\s*\}(\s+#.*)?$", s):
            raise YAMLError("flow mappings are not supported (only {} is)", no)
        return {}
    if s[0] in _UNSUPPORTED_START:
        raise YAMLError(f"unsupported YAML syntax starting with {s[0]!r}", no)
    m = re.search(r"\s#", s)
    if m:
        s = s[: m.start()].rstrip()
    return _plain(s)


def _plain(s: str) -> Any:
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if s in ("null", "Null", "NULL", "~"):
        return None
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


def _flow_sequence(s: str, no: int) -> list:
    items: list[Any] = []
    i = 1
    buf = ""
    while i < len(s):
        c = s[i]
        if c in ("'", '"') and not buf.strip():
            value, rest = _quoted(s[i:], no)
            items.append(value)
            i = len(s) - len(rest)
            while i < len(s) and s[i] == " ":
                i += 1
            if s[i : i + 1] == ",":
                i += 1
                buf = ""
                continue
            if s[i : i + 1] == "]":
                _only_comment(s[i + 1 :], no)
                return items
            raise YAMLError("expected ',' or ']' in flow sequence", no)
        if c in "[{":
            raise YAMLError("nested flow collections are not supported", no)
        if c == ",":
            if not buf.strip():
                raise YAMLError("empty item in flow sequence", no)
            items.append(_plain(buf.strip()))
            buf = ""
        elif c == "]":
            if buf.strip():
                items.append(_plain(buf.strip()))
            elif items:
                raise YAMLError("trailing comma in flow sequence", no)
            _only_comment(s[i + 1 :], no)
            return items
        else:
            buf += c
        i += 1
    raise YAMLError("unterminated flow sequence", no)
