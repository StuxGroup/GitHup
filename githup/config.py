"""Load and validate a GitHup config (`.githup.yml` or `.githup.json`)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import yamlish

CONFIG_NAMES = (".githup.yml", ".githup.yaml", ".githup.json")
DEFAULT_EXPECTED = ((200, 399),)
DEFAULT_ACCENT = "#3ba7ff"
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# ${NAME}, ${{ secrets.NAME }}, ${{ env.NAME }}
_PLACEHOLDER = re.compile(r"\$\{\{\s*(?:(secrets|env)\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\}\}|\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """The config file is missing, malformed or invalid."""


@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass(frozen=True)
class Site:
    name: str = "Status"
    description: str = ""
    logo: str = ""
    favicon: str = ""
    cname: str = ""
    accent: str = DEFAULT_ACCENT
    legal: str = ""
    footer_links: tuple[Link, ...] = ()
    live_data: bool = True
    refresh: int = 60
    show_urls: bool = True


@dataclass(frozen=True)
class Monitor:
    name: str
    slug: str
    url: str
    method: str = "GET"
    expected: tuple[tuple[int, int], ...] = DEFAULT_EXPECTED
    timeout: float = 10.0
    retries: int = 2
    retry_delay: float = 2.0
    max_response_time: int | None = None
    headers: tuple[tuple[str, str], ...] = ()
    body: str | None = None
    follow_redirects: bool = True
    verify_tls: bool = True
    description: str = ""
    show_url: bool | None = None


@dataclass(frozen=True)
class Incidents:
    enabled: bool = True
    assignees: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    site: Site
    monitors: tuple[Monitor, ...]
    incidents: Incidents = field(default_factory=Incidents)
    keep_months: int = 0
    path: str = ""

    def monitor(self, slug: str) -> Monitor | None:
        return next((m for m in self.monitors if m.slug == slug), None)


# --------------------------------------------------------------------------
# helpers


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:64].strip("-") or "monitor"


def parse_expected(value: Any, where: str) -> tuple[tuple[int, int], ...]:
    """Turn ``[200, "300-399", 404]`` into ``((200, 200), (300, 399), (404, 404))``."""
    if value is None:
        return DEFAULT_EXPECTED
    if isinstance(value, (int, str)):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: 'expected' must be a non-empty list of status codes or ranges")
    ranges = []
    for item in value:
        if isinstance(item, bool):
            raise ConfigError(f"{where}: invalid status code {item!r}")
        if isinstance(item, int):
            lo = hi = item
        elif isinstance(item, str) and re.fullmatch(r"\s*\d{3}\s*-\s*\d{3}\s*", item):
            lo, hi = (int(p) for p in item.split("-"))
        elif isinstance(item, str) and re.fullmatch(r"\s*\d{3}\s*", item):
            lo = hi = int(item)
        elif isinstance(item, str) and re.fullmatch(r"[1-5]xx", item.strip().lower()):
            lo = int(item.strip()[0]) * 100
            hi = lo + 99
        else:
            raise ConfigError(f"{where}: invalid status code or range {item!r}")
        if not (100 <= lo <= hi <= 599):
            raise ConfigError(f"{where}: status range {item!r} is outside 100-599")
        ranges.append((lo, hi))
    return tuple(ranges)


def placeholders(text: str) -> list[str]:
    """Names of the environment/secret placeholders used in ``text``."""
    return [m.group(2) or m.group(3) for m in _PLACEHOLDER.finditer(text)]


def expand(text: str, env: dict[str, str] | None = None, secrets: dict[str, str] | None = None) -> str:
    """Replace ``${NAME}`` / ``${{ secrets.NAME }}`` / ``${{ env.NAME }}``.

    Secrets come from the action's ``secrets`` input (``toJSON(secrets)``)
    and fall back to an environment variable of the same name, so a value
    can be passed either way. Raises KeyError naming the missing variable.
    """
    env = os.environ if env is None else env
    secrets = secrets or {}

    def repl(m: re.Match) -> str:
        scope, name = m.group(1), m.group(2) or m.group(3)
        if scope == "secrets" and name in secrets:
            return str(secrets[name])
        if name in env:
            return env[name]
        if name in secrets:
            return str(secrets[name])
        raise KeyError(name)

    return _PLACEHOLDER.sub(repl, text)


def _check_keys(data: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})")


def _str(data: dict, key: str, where: str, default: str = "") -> str:
    value = data.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ConfigError(f"{where}: '{key}' must be a string")
    return str(value)


def _bool(data: dict, key: str, where: str, default: bool) -> bool:
    value = data.get(key, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: '{key}' must be true or false")
    return value


def _num(data: dict, key: str, where: str, default, *, minimum=0, integer=False):
    value = data.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (integer and not isinstance(value, int)):
        raise ConfigError(f"{where}: '{key}' must be a {'whole ' if integer else ''}number")
    if value < minimum:
        raise ConfigError(f"{where}: '{key}' must be at least {minimum}")
    return value


def _url(value: str, where: str, key: str, required: bool = False) -> str:
    if not value:
        if required:
            raise ConfigError(f"{where}: '{key}' is required")
        return ""
    if not re.match(r"^https?://", value, re.I) and not value.startswith("${"):
        raise ConfigError(f"{where}: '{key}' must be an http(s) URL, got {value!r}")
    return value


# --------------------------------------------------------------------------
# sections


def _parse_site(data: Any) -> Site:
    where = "site"
    if data is None:
        return Site()
    if not isinstance(data, dict):
        raise ConfigError("site: must be a mapping")
    _check_keys(data, {"name", "description", "logo", "favicon", "cname", "accent", "legal",
                       "footer_links", "live_data", "refresh", "show_urls"}, where)
    accent = _str(data, "accent", where, DEFAULT_ACCENT)
    if not _HEX.match(accent):
        raise ConfigError(f"site: 'accent' must be a hex colour like #a349a4, got {accent!r}")
    if len(accent) == 4:
        accent = "#" + "".join(c * 2 for c in accent[1:])
    links = []
    raw_links = data.get("footer_links") or []
    if not isinstance(raw_links, list):
        raise ConfigError("site: 'footer_links' must be a list")
    for n, item in enumerate(raw_links, start=1):
        lw = f"site.footer_links[{n}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{lw}: must be a mapping with 'label' and 'url'")
        _check_keys(item, {"label", "url"}, lw)
        label = _str(item, "label", lw)
        if not label:
            raise ConfigError(f"{lw}: 'label' is required")
        links.append(Link(label, _url(_str(item, "url", lw), lw, "url", required=True)))
    cname = _str(data, "cname", where).strip()
    if cname and not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cname):
        raise ConfigError(f"site: 'cname' must be a bare domain like status.example.com, got {cname!r}")
    return Site(
        name=_str(data, "name", where, "Status") or "Status",
        description=_str(data, "description", where),
        logo=_url(_str(data, "logo", where), where, "logo"),
        favicon=_url(_str(data, "favicon", where), where, "favicon"),
        cname=cname,
        accent=accent.lower(),
        legal=_url(_str(data, "legal", where), where, "legal"),
        footer_links=tuple(links),
        live_data=_bool(data, "live_data", where, True),
        refresh=int(_num(data, "refresh", where, 60, minimum=0, integer=True)),
        show_urls=_bool(data, "show_urls", where, True),
    )


_MONITOR_KEYS = {"name", "slug", "url", "method", "expected", "timeout", "retries", "retry_delay",
                 "max_response_time", "headers", "body", "follow_redirects", "verify_tls",
                 "description", "show_url"}
_DEFAULT_KEYS = _MONITOR_KEYS - {"name", "slug", "url", "description", "body", "show_url"}


def _parse_headers(value: Any, where: str) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    pairs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, list):
        items = []
        for item in value:
            if isinstance(item, dict) and set(item) == {"name", "value"}:
                items.append((item["name"], item["value"]))
            elif isinstance(item, str) and ":" in item:
                k, v = item.split(":", 1)
                items.append((k.strip(), v.strip()))
            else:
                raise ConfigError(f"{where}: each header must be 'Name: value' or {{name, value}}")
    else:
        raise ConfigError(f"{where}: 'headers' must be a mapping or a list")
    for k, v in items:
        if not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", k):
            raise ConfigError(f"{where}: invalid header name {k!r}")
        if v is None or isinstance(v, (dict, list)):
            raise ConfigError(f"{where}: header {k!r} needs a value")
        pairs.append((k, str(v)))
    return tuple(pairs)


def _parse_monitor(data: Any, n: int, defaults: dict) -> Monitor:
    where = f"monitors[{n}]"
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: must be a mapping")
    _check_keys(data, _MONITOR_KEYS, where)
    merged = {**defaults, **data}
    name = _str(merged, "name", where).strip()
    if not name:
        raise ConfigError(f"{where}: 'name' is required")
    where = f"monitors[{n}] ({name})"
    slug = _str(merged, "slug", where).strip() or slugify(name)
    if not _SLUG.match(slug):
        raise ConfigError(f"{where}: slug {slug!r} may only use a-z, 0-9 and '-'")
    method = _str(merged, "method", where, "GET").upper()
    if method not in METHODS:
        raise ConfigError(f"{where}: unsupported method {method!r}")
    mrt = merged.get("max_response_time")
    if mrt is not None:
        mrt = int(_num(merged, "max_response_time", where, None, minimum=1, integer=True))
    show_url = merged.get("show_url")
    if show_url is not None and not isinstance(show_url, bool):
        raise ConfigError(f"{where}: 'show_url' must be true or false")
    body = merged.get("body")
    return Monitor(
        name=name,
        slug=slug,
        url=_url(_str(merged, "url", where).strip(), where, "url", required=True),
        method=method,
        expected=parse_expected(merged.get("expected"), where),
        timeout=float(_num(merged, "timeout", where, 10.0, minimum=1)),
        retries=int(_num(merged, "retries", where, 2, integer=True)),
        retry_delay=float(_num(merged, "retry_delay", where, 2.0)),
        max_response_time=mrt,
        headers=_parse_headers(merged.get("headers"), where),
        body=None if body is None else str(body),
        follow_redirects=_bool(merged, "follow_redirects", where, True),
        verify_tls=_bool(merged, "verify_tls", where, True),
        description=_str(merged, "description", where),
        show_url=show_url,
    )


def _parse_incidents(data: Any) -> Incidents:
    if data is None:
        return Incidents()
    if isinstance(data, bool):
        return Incidents(enabled=data)
    if not isinstance(data, dict):
        raise ConfigError("incidents: must be true/false or a mapping")
    _check_keys(data, {"enabled", "assignees", "labels"}, "incidents")
    out = {}
    for key in ("assignees", "labels"):
        value = data.get(key) or []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"incidents: '{key}' must be a list of strings")
        out[key] = tuple(value)
    return Incidents(enabled=_bool(data, "enabled", "incidents", True), **out)


def parse(data: Any, path: str = "") -> Config:
    """Validate an already-decoded config document."""
    if not isinstance(data, dict):
        raise ConfigError("the config must be a mapping with 'site' and 'monitors'")
    _check_keys(data, {"site", "defaults", "monitors", "incidents", "data"}, "config")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("defaults: must be a mapping")
    _check_keys(defaults, _DEFAULT_KEYS, "defaults")
    raw_monitors = data.get("monitors")
    if not isinstance(raw_monitors, list) or not raw_monitors:
        raise ConfigError("monitors: must be a non-empty list")
    monitors = tuple(_parse_monitor(m, n, defaults) for n, m in enumerate(raw_monitors, start=1))
    seen: set[str] = set()
    for m in monitors:
        if m.slug in seen:
            raise ConfigError(f"monitors: duplicate slug {m.slug!r} (set 'slug' explicitly)")
        seen.add(m.slug)
    data_opts = data.get("data") or {}
    if not isinstance(data_opts, dict):
        raise ConfigError("data: must be a mapping")
    _check_keys(data_opts, {"keep_months"}, "data")
    return Config(
        site=_parse_site(data.get("site")),
        monitors=monitors,
        incidents=_parse_incidents(data.get("incidents")),
        keep_months=int(_num(data_opts, "keep_months", "data", 0, integer=True)),
        path=path,
    )


def find(root: str | os.PathLike = ".") -> Path:
    for name in CONFIG_NAMES:
        p = Path(root) / name
        if p.is_file():
            return p
    raise ConfigError(f"no config found: create one of {', '.join(CONFIG_NAMES)} in {Path(root).resolve()}")


def load(path: str | os.PathLike | None = None) -> Config:
    p = Path(path) if path else find()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {p}: {exc}") from exc
    try:
        data = json.loads(text) if p.suffix == ".json" else yamlish.loads(text)
    except (ValueError, yamlish.YAMLError) as exc:
        raise ConfigError(f"{p}: {exc}") from exc
    return parse(data, str(p))
