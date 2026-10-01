"""Default texts for the generated legal pages (``legal:`` in the config).

A GitHup status page is static: no accounts, no forms, no cookies, no
analytics. The texts say exactly that and are filled in from the ``legal:``
block (operator, company, contact, host, effective date). Every value is
escaped on the way in.
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlparse

GITHUP_URL = "https://github.com/StuxGroup/GitHup"

# (slug, title, one-line description) in hub order.
PAGES = (
    ("privacy", "Privacy Policy", "What we collect: nothing about you."),
    ("terms", "Terms and Ethics", "Using the status page fairly."),
    ("cookies", "Cookies Policy", "We don't use any."),
    ("imprint", "Imprint", "Who runs this page and how to reach us."),
    ("disclaimer", "Disclaimer", "Accuracy, accessibility, copyright and security."),
    ("opt-out", "Opt-Out Preferences", "Your privacy choices."),
)
HUB_SUB = "The fine print for {name}."


def _host_of(url: str) -> str:
    return urlparse(url).hostname or ""


class Context:
    """Escaped values shared by every legal text."""

    def __init__(self, config):
        site, legal = config.site, config.legal
        self.site_name = site.name
        self.name = escape(site.name)
        self.operator = escape(legal.operator or site.name)
        self.company = escape(legal.company)
        self.contact = legal.contact
        self.host = escape(legal.host)
        self.effective = legal.effective
        self.domain = site.cname or _host_of(site.url)
        self.logo_host = _host_of(site.logo)

    @property
    def this(self) -> str:
        """How the texts refer to the page."""
        return escape(self.domain) if self.domain else self.name

    def mail(self) -> str:
        if not self.contact:
            return "by opening an Issue on this status page's GitHub repository"
        return f'at <a href="mailto:{escape(self.contact)}">{escape(self.contact)}</a>'


def _sections(*items: tuple[str, str]) -> str:
    return "".join(f"<h2>{h}</h2>\n{body}\n" for h, body in items)


def _privacy(c: Context) -> str:
    domain = f"{c.this} is" if c.domain else "This page is"
    images = (f'<p>The logo and icon are loaded from <strong>{escape(c.logo_host)}</strong>. '
              "Your browser contacts that host to fetch them, as it would for any image.</p>") if c.logo_host else ""
    return _sections(
        ("The short version",
         f"<p>{domain} a static page that shows whether {c.name}'s services are up. It has no accounts, forms, "
         "analytics, tracking or advertising, and it collects no personal data about you.</p>"),
        ("Hosting",
         f"<p>The page is hosted on <strong>{c.host}</strong>. Our host, and the DNS or proxy provider of a custom domain, "
         "may process your IP address and browser details to deliver the page and protect it from abuse, under their own "
         "privacy policies. We don't receive or keep those logs.</p>"),
        ("Live status data",
         "<p>To stay current, the page reloads its status data from this site and from raw.githubusercontent.com "
         "(GitHub). Only the monitoring data is fetched; nothing about you is sent.</p>"),
        *((("Images", images),) if images else ()),
        ("Your rights",
         "<p>Under data protection law (such as the UK and EU GDPR) you can ask what personal data we hold about you. "
         f"For this page the answer is none, but you're welcome to ask {c.mail()}.</p>"),
    )


def _terms(c: Context) -> str:
    return _sections(
        ("What this page is",
         f"<p>{c.this} reports the availability of {c.name}'s websites and services, as seen by automated checks "
         "that run on GitHub's servers.</p>"),
        ("Using it",
         "<p>You're welcome to read, link to and share this page. Please don't scrape it aggressively; its data is also "
         "available as <code>summary.json</code>, which is lighter for everyone.</p>"),
        ("No guarantee",
         "<p>The page is provided &ldquo;as is&rdquo;. Checks can run late or be skipped, and a service can be "
         "unreachable for you while it looks fine from here, or the other way round. It is not a service-level "
         "agreement.</p>"),
        ("Changes",
         "<p>We may update these terms. The current version always lives on this page.</p>"),
    )


def _cookies(c: Context) -> str:
    return _sections(
        ("No cookies",
         "<p>This page sets no cookies. There are no analytics, advertising or tracking scripts, so there's no cookie "
         "banner.</p>"),
        ("Browser storage",
         "<p>If you switch between the light and dark themes, your choice is saved in your browser's "
         "<code>localStorage</code>. It never leaves your device, and you can clear it in your browser's site data "
         "settings.</p>"),
        ("Our hosts",
         f"<p>{c.host} and any proxy in front of a custom domain are third parties. If one of them sets a strictly "
         "necessary security cookie, that is outside our control; see its own cookie documentation.</p>"),
    )


def _imprint(c: Context) -> str:
    entity = f"<p>{c.this} is operated by <strong>{c.operator}</strong>.</p>"
    if c.company:
        entity += f"\n<p>{c.company}</p>"
    contact = (f"<p>Questions, including legal, privacy or copyright matters: "
               f'<a href="mailto:{escape(c.contact)}">{escape(c.contact)}</a>.</p>') if c.contact else (
        "<p>Reach us by opening an Issue on this status page's GitHub repository.</p>")
    return _sections(
        ("Operator", entity),
        ("Hosting",
         f'<p>Hosted on <strong>{c.host}</strong> and built by <a href="{GITHUP_URL}">GitHup</a>.</p>'),
        ("Contact", contact),
    )


def _disclaimer(c: Context) -> str:
    return _sections(
        ("Accuracy",
         "<p>Figures reflect what automated checks from GitHub's runners saw. Uptime percentages are rounded down and "
         "daily history uses UTC days.</p>"),
        ("Copyright",
         f"<p>The {c.name} name, logos and branding belong to {c.operator}. The page is built with "
         f'<a href="{GITHUP_URL}">GitHup</a>, which is open source under the MIT License.</p>'),
        ("Accessibility",
         f"<p>We aim to meet WCAG 2.1 AA. If something gets in your way, tell us {c.mail()} and we'll fix it.</p>"),
        ("Security",
         f"<p>Found a vulnerability in one of our services? Please tell us {c.mail()} before disclosing it publicly, "
         "so we can fix it first.</p>"),
        ("Third-party links",
         "<p>This page links to other sites. We aren't responsible for their content, policies or practices.</p>"),
    )


def _opt_out(c: Context) -> str:
    return _sections(
        ("No sale or sharing of data",
         "<p>Laws like California's CCPA/CPRA let you opt out of the sale or sharing of your personal data. This page "
         "collects none, so there is nothing to sell, share or opt out of.</p>"),
        ("Do Not Track and Global Privacy Control",
         "<p>Nothing here tracks you, so these signals have no additional effect. We honour them anyway.</p>"),
        ("Questions", f"<p>Ask us {c.mail()}.</p>"),
    )


_BODIES = {"privacy": _privacy, "terms": _terms, "cookies": _cookies, "imprint": _imprint,
           "disclaimer": _disclaimer, "opt-out": _opt_out}


def body(slug: str, config) -> str:
    """The HTML body (sections) of one legal sub-page."""
    return _BODIES[slug](Context(config))
