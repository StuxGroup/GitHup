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
# Responses slower than this (ms) count as degraded. 0 or false turns the check off.
DEFAULT_MAX_RESPONSE_TIME = 15000
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
class Copyright:
    """The optional ``site.copyright`` block: ``holder`` and the ``start`` year of the project."""

    holder: str
    start: int | None = None


@dataclass(frozen=True)
class Site:
    name: str = "Status"
    description: str = ""
    logo: str = ""
    favicon: str = ""
    cname: str = ""
    url: str = ""
    accent: str = DEFAULT_ACCENT
    legal: str = ""
    changelog: str = ""  # deprecated: accepted but ignored
    version: str = ""  # deprecated: accepted but ignored
    notice: str = ""
    footer_links: tuple[Link, ...] = ()
    live_data: bool = True
    refresh: int = 60
    show_urls: bool = True
    copyright: Copyright | None = None


@dataclass(frozen=True)
class Legal:
    """The optional ``legal:`` block: texts for the generated /legal/ pages."""

    operator: str = ""  # shown as the operator; defaults to the site name
    company: str = ""  # free-text legal entity line for the Imprint
    contact: str = ""  # contact email
    host: str = "GitHub Pages"
    effective: str = ""  # date shown on every legal page


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
    max_response_time: int | None = DEFAULT_MAX_RESPONSE_TIME
    headers: tuple[tuple[str, str], ...] = ()
    body: str | None = None
    follow_redirects: bool = True
    verify_tls: bool = True
    description: str = ""
    show_url: bool | None = None
    group: str = ""  # slug of the group this monitor belongs to ("" = ungrouped)


@dataclass(frozen=True)
class GroupLink:
    """A plain link shown in a group's section. Never probed, never part of any status."""

    name: str
    url: str
    description: str = ""


@dataclass(frozen=True)
class Group:
    name: str
    slug: str
    description: str = ""
    collapsed: bool = False
    monitors: tuple[str, ...] = ()  # monitor slugs, in config order (may be empty for a links-only group)
    links: tuple[GroupLink, ...] = ()


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
    groups: tuple[Group, ...] = ()
    legal: Legal | None = None
    warnings: tuple[str, ...] = ()  # e.g. deprecated keys; the CLI logs them

    def monitor(self, slug: str) -> Monitor | None:
        return next((m for m in self.monitors if m.slug == slug), None)

    def group(self, slug: str) -> Group | None:
        return next((g for g in self.groups if g.slug == slug), None)

    def ungrouped(self) -> tuple[Monitor, ...]:
        return tuple(m for m in self.monitors if not m.group)

    def sections(self) -> list[tuple[Group | None, tuple[Monitor, ...]]]:
        """Monitors in display order: ungrouped ones first, then each group."""
        out: list[tuple[Group | None, tuple[Monitor, ...]]] = []
        if self.ungrouped():
            out.append((None, self.ungrouped()))
        for g in self.groups:
            out.append((g, tuple(m for m in self.monitors if m.group == g.slug)))
        return out


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


def _parse_legal(data: Any) -> Legal | None:
    where = "legal"
    if data is None or data is False:
        return None
    if data is True:
        return Legal()
    if not isinstance(data, dict):
        raise ConfigError("legal: must be a mapping (operator, company, contact, host, effective)")
    _check_keys(data, {"operator", "company", "contact", "host", "effective"}, where)
    contact = _str(data, "contact", where).strip()
    if contact and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact) and not contact.startswith("${"):
        raise ConfigError(f"legal: 'contact' must be an email address, got {contact!r}")
    return Legal(
        operator=_str(data, "operator", where).strip(),
        company=_str(data, "company", where).strip(),
        contact=contact,
        host=_str(data, "host", where, "GitHub Pages").strip() or "GitHub Pages",
        effective=_str(data, "effective", where).strip(),
    )


def _parse_copyright(data: Any) -> Copyright | None:
    where = "site.copyright"
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ConfigError("site.copyright: must be a mapping (holder, start)")
    _check_keys(data, {"holder", "start"}, where)
    holder = _str(data, "holder", where).strip()
    if not holder:
        raise ConfigError("site.copyright: 'holder' is required (who owns the copyright)")
    start = data.get("start")
    if isinstance(start, str) and re.fullmatch(r"[0-9]{4}", start.strip()):
        start = int(start.strip())
    if start is not None and (isinstance(start, bool) or not isinstance(start, int) or not 1900 <= start <= 2999):
        raise ConfigError(f"site.copyright: 'start' must be a four-digit year like 2024, got {start!r}")
    return Copyright(holder=holder, start=start)


def _parse_site(data: Any) -> Site:
    where = "site"
    if data is None:
        return Site()
    if not isinstance(data, dict):
        raise ConfigError("site: must be a mapping")
    _check_keys(data, {"name", "description", "logo", "favicon", "cname", "url", "accent", "legal",
                       "changelog", "version", "notice", "footer_links", "live_data", "refresh", "show_urls",
                       "copyright"}, where)
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
    url = _url(_str(data, "url", where).strip(), where, "url")
    return Site(
        name=_str(data, "name", where, "Status") or "Status",
        description=_str(data, "description", where),
        logo=_url(_str(data, "logo", where), where, "logo"),
        favicon=_url(_str(data, "favicon", where), where, "favicon"),
        cname=cname,
        url=url,
        accent=accent.lower(),
        legal=_url(_str(data, "legal", where), where, "legal"),
        changelog=_url(_str(data, "changelog", where), where, "changelog"),
        version=_str(data, "version", where).strip().lstrip("vV"),
        notice=_str(data, "notice", where).strip(),
        footer_links=tuple(links),
        live_data=_bool(data, "live_data", where, True),
        refresh=int(_num(data, "refresh", where, 60, minimum=0, integer=True)),
        show_urls=_bool(data, "show_urls", where, True),
        copyright=_parse_copyright(data.get("copyright")),
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


def _parse_monitor(data: Any, n: int, defaults: dict, group: str = "", prefix: str = "monitors") -> Monitor:
    where = f"{prefix}[{n}]"
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: must be a mapping")
    _check_keys(data, _MONITOR_KEYS, where)
    merged = {**defaults, **data}
    name = _str(merged, "name", where).strip()
    if not name:
        raise ConfigError(f"{where}: 'name' is required")
    where = f"{prefix}[{n}] ({name})"
    slug = _str(merged, "slug", where).strip() or slugify(name)
    if not _SLUG.match(slug):
        raise ConfigError(f"{where}: slug {slug!r} may only use a-z, 0-9 and '-'")
    method = _str(merged, "method", where, "GET").upper()
    if method not in METHODS:
        raise ConfigError(f"{where}: unsupported method {method!r}")
    mrt = merged.get("max_response_time", DEFAULT_MAX_RESPONSE_TIME)
    if mrt is False or mrt == 0:
        mrt = None  # degraded-by-slowness turned off
    elif mrt is None:
        mrt = DEFAULT_MAX_RESPONSE_TIME
    else:
        mrt = int(_num({"max_response_time": mrt}, "max_response_time", where, None, minimum=1, integer=True))
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
        group=group,
    )


def _parse_group_links(raw: Any, where: str) -> tuple[GroupLink, ...]:
    if not isinstance(raw, list):
        raise ConfigError(f"{where}: 'links' must be a list")
    out = []
    for i, item in enumerate(raw, start=1):
        lw = f"{where}.links[{i}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{lw}: must be a mapping with 'name' and 'url'")
        _check_keys(item, {"name", "url", "description"}, lw)
        name = _str(item, "name", lw).strip()
        if not name:
            raise ConfigError(f"{lw}: 'name' is required")
        lw = f"{lw} ({name})"
        url = _url(_str(item, "url", lw).strip(), lw, "url", required=True)
        out.append(GroupLink(name=name, url=url, description=_str(item, "description", lw).strip()))
    return tuple(out)


def _parse_group(data: Any, n: int, defaults: dict) -> tuple[Group, list[Monitor]]:
    where = f"groups[{n}]"
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: must be a mapping with 'name' and 'monitors' and/or 'links'")
    _check_keys(data, {"name", "slug", "description", "collapsed", "monitors", "links"}, where)
    name = _str(data, "name", where).strip()
    if not name:
        raise ConfigError(f"{where}: 'name' is required")
    where = f"groups[{n}] ({name})"
    slug = _str(data, "slug", where).strip() or slugify(name)
    if not _SLUG.match(slug):
        raise ConfigError(f"{where}: slug {slug!r} may only use a-z, 0-9 and '-'")
    raw = data.get("monitors")
    raw_links = data.get("links")
    if raw is not None and not isinstance(raw, list):
        raise ConfigError(f"{where}: 'monitors' must be a list")
    if not raw and not raw_links:
        raise ConfigError(f"{where}: needs at least one monitor in 'monitors' or one entry in 'links'")
    links = _parse_group_links(raw_links, where) if raw_links is not None else ()
    raw = raw or []
    monitors = [_parse_monitor(m, i, defaults, group=slug, prefix=f"{where}.monitors")
                for i, m in enumerate(raw, start=1)]
    group = Group(
        name=name,
        slug=slug,
        description=_str(data, "description", where),
        collapsed=_bool(data, "collapsed", where, False),
        monitors=tuple(m.slug for m in monitors),
        links=links,
    )
    return group, monitors


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
        raise ConfigError("the config must be a mapping with 'site' and 'monitors' (or 'groups')")
    _check_keys(data, {"site", "defaults", "monitors", "groups", "incidents", "data", "legal"}, "config")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("defaults: must be a mapping")
    _check_keys(defaults, _DEFAULT_KEYS, "defaults")
    raw_monitors = data.get("monitors")
    raw_groups = data.get("groups")
    if raw_monitors is not None and not isinstance(raw_monitors, list):
        raise ConfigError("monitors: must be a list")
    if raw_groups is not None and not isinstance(raw_groups, list):
        raise ConfigError("groups: must be a list")
    if not raw_monitors and not raw_groups:
        raise ConfigError("monitors: must be a non-empty list (or define 'groups' with monitors)")
    monitors = [_parse_monitor(m, n, defaults) for n, m in enumerate(raw_monitors or [], start=1)]
    groups = []
    for n, g in enumerate(raw_groups or [], start=1):
        group, grouped = _parse_group(g, n, defaults)
        if any(x.slug == group.slug for x in groups):
            raise ConfigError(f"groups: duplicate slug {group.slug!r} (set 'slug' explicitly)")
        groups.append(group)
        monitors.extend(grouped)
    seen: set[str] = set()
    for m in monitors:
        if m.slug in seen:
            raise ConfigError(f"monitors: duplicate slug {m.slug!r} (set 'slug' explicitly)")
        seen.add(m.slug)
    data_opts = data.get("data") or {}
    if not isinstance(data_opts, dict):
        raise ConfigError("data: must be a mapping")
    _check_keys(data_opts, {"keep_months"}, "data")
    site = _parse_site(data.get("site"))
    warnings = tuple(
        f"site.{key} is deprecated and ignored: the footer only shows GitHup's own version and changelog (remove it)"
        for key in ("changelog", "version") if getattr(site, key))
    return Config(
        site=site,
        monitors=tuple(monitors),
        incidents=_parse_incidents(data.get("incidents")),
        keep_months=int(_num(data_opts, "keep_months", "data", 0, integer=True)),
        path=path,
        groups=tuple(groups),
        legal=_parse_legal(data.get("legal")),
        warnings=warnings,
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
