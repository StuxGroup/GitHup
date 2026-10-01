# Changelog

All notable changes to GitHup are documented here. GitHup follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); the floating `v1` tag always points
at the newest 1.x.y release.

## v1.8.0

### Added

- An opt-in `fill-gaps` input for `check` (off by default, CLI `--fill-gaps`) with `repeat` (1 to 6, default 1) and `repeat-interval` (seconds, at least 60, default 300). When GitHub runs the schedule late and the last check is 1.5 × `repeat-interval` or more old, one run checks up to `repeat` times, spaced `repeat-interval` apart on a monotonic clock. Every round probes, records, commits and pushes, and handles incident Issues. Before each extra round GitHup re-reads the newest check (fetching the remote) and stops early if another run caught up. A run that is on time does one round, so a healthy schedule costs the same as before
- A `::warning::` when a check run starts and the last check is overdue while `fill-gaps` is off, and a `::notice::` when `repeat` is set but ignored because `fill-gaps` is off
- A "Schedule delays" section in the README with the risks of enabling `fill-gaps`, and the options (commented out) in the workflow template

### Changed

- `status-changed` is true when any round changed a status (and on the first run); `status` and `down` come from the last round
- Invalid `repeat` or `repeat-interval` values are input errors (exit code 2)

### Fixed

- A round whose commit cannot be pushed no longer stops later rounds: it is logged, the next round pushes the pending commits, and the step fails at the end only if a push failed

## v1.7.0

### Added

- An optional `site.copyright` block (`holder`, `start` year) that adds "Copyright © START–CURRENT HOLDER" to the footer of every generated page: the start year alone in the first year, then START–CURRENT. The year is worked out at build time, and status pages rebuild at least hourly, so it rolls over on 1 January without edits. The holder is required, `start` must be a four-digit year, and unknown keys are config errors

## v1.6.0

### Added

- An optional `legal:` config block (`operator`, `company`, `contact`, `host`, `effective`) that makes `site` mode generate a legal hub at `/legal/` and six sub-pages (`privacy`, `terms`, `cookies`, `imprint`, `disclaimer`, `opt-out`) in the status page's own template: light and dark themes, the site banner and the same footer. The default texts are written for status pages. Unknown keys are config errors
- A themed `404.html` with the header, banner, footer and a link home
- `sitemap.xml`, a `robots.txt` with a `Sitemap:` line (an existing one is kept) and a `/sitemap/` page listing the pages, with a **Sitemap** footer link, whenever a canonical URL is known
- A `site.url` config key: the canonical base URL for the sitemap when there is no `site.cname`

### Changed

- The footer shows one version only, **Powered by GitHup vX.Y.Z**, and it links to the GitHup changelog at `https://githup.stux.group/changelogs/#githup` instead of the GitHub release
- With a `legal:` block, the footer's **Boring Legal Stuff** link points at the generated `/legal/`; it wins over `site.legal`

### Fixed

- The 404 page no longer redirects through a meta refresh with a link that broke in subfolders; it links to the site root when the base URL is known

### Removed

- The footer's own repo-version link (`vX.Y.Z` / **Changelog**) that `site.changelog` and `site.version` used to add

### Deprecated

- `site.changelog` and `site.version` are still accepted so existing configs keep working, but they are ignored and a warning is logged

## v1.5.0

### Added

- A `site.notice` config key: its text shows as a **Notice** banner across the top of the status page
- In dev mode, `?banner=soon,maintenance,site` previews the other banner styles on the local page

### Changed

- The dev-mode banner is the shared Stux site banner: a muted strip in the page's own colours with a label chip and a faint icon pattern, instead of yellow hazard stripes. It stays at the top of the page and pushes the page down by its exact height, so it never covers anything, including when it wraps on phones
- The footer's **Powered by GitHup | A Stux.Group Service** is muted until hovered or focused: the GitHup mark is grey and dimmed and the text uses the muted colour, and both light up on hover. The mark keeps the same filter functions in every state, so the hover animates smoothly instead of snapping
- The banner's CSS and JavaScript are only included on pages that show a banner

## v1.4.0

### Added

- Monitor groups: a top-level `groups:` list whose entries take `name`, `slug`, `description`, `collapsed` and their own `monitors`, shown on the status page as collapsible sections, each with a combined status pill that live refresh keeps up to date
- `collapsed: true` starts a group closed, but it opens itself (at build time and on live refresh) while one of its monitors is down or degraded
- `readme` mode adds a **Group** column to the status table when the config has groups
- A `site-url` input (`--site-url`) for `readme` mode that sets the page the table links to, so a table can live in another repo's README, like an organisation's `.github` profile; the README shows how
- `examples/.githup.yml` (and so the local dev server) shows groups: *Website* ungrouped, then *Platform* and a collapsed *Assets*
- `site.changelog` and `site.version`: with a changelog URL set, the footer's first link shows your status page's own version (`vX.Y.Z`, read from the `VERSION.md` next to the config unless `site.version` is set) and links to that page
- The status page footer shows the GitHup version (**Powered by GitHup v1.4.0**), linking to that release

### Changed

- `monitors:` is now optional when `groups:` is set; slugs stay unique across both, so moving a monitor into a group keeps its data and incidents
- Configs without `groups` render exactly as before

## v1.3.0

### Changed

- `readme` mode's "Live status page" link now comes from the repository's GitHub Pages settings when `site.cname` is empty, so sites deployed with Actions (whose custom domain lives in the Pages settings) link to their real address instead of the default `owner.github.io/repo/`; it falls back to that default when the Pages API can't be read (it needs a token with `pages: read`)

## v1.2.1

### Changed

- The action now sets up Python with `actions/setup-python@v7`, which runs on Node 24, clearing GitHub's Node 20 deprecation warning in every workflow that uses GitHup
- `templates/githup.yml`, the README examples and CI use `actions/checkout@v7` (CI also moves to `actions/setup-python@v7` and `actions/setup-node@v7` with Node 24) (and `actions/upload-pages-artifact@v5` in the Actions deployment example)

## v1.2.0

### Added

- A `site-dir` input for `site` mode that sets where the page is built, and a matching `site-dir` output; with `deploy: "false"` this lets you publish with `actions/deploy-pages` or nest the status page in a subfolder of a larger site
- A "Deploying with Actions" section in the README, and links to the new website ([githup.stux.group](https://githup.stux.group)) and its live demo ([githup.stux.group/demo](https://githup.stux.group/demo/))

## v1.1.2

### Added

- PNG brand assets rendered from the SVGs: `assets/icon.png` (512 × 512, transparent) and `assets/social-preview.png` (1280 × 640) for the repository's GitHub social preview, showing the logo, tagline and "A Stux.Group Service"

## v1.1.1

### Fixed

- The GitHup wordmark (`assets/logo.svg`, `assets/logo-dark.svg`) had a wide empty margin to the right of the text; its canvas is trimmed from 264 to 220 px wide, and the README logo size matches

## v1.1.0

### Added

- GitHup's own logo and icon (`assets/icon.svg`, `assets/logo.svg`, `assets/logo-dark.svg`): a pulse line rising into an "up" arrow on the purple-to-blue gradient
- The status page falls back to the GitHup icon (inlined as a data URI) as its favicon when the config sets no `logo` or `favicon`

### Changed

- The README and CONTRIBUTING headers show the GitHup logo and icon instead of the shared Stux.Group mark, and the README gains a tagline and a light/dark `<picture>` logo
- Stux.Group service branding: the README, CONTRIBUTING and status page footer now present GitHup as "A Stux.Group Service", linking to `https://services.stux.group`, like the other Stux.Group services
- The status page footer reads "Powered by GitHup | A Stux.Group Service", with the inline GitHup icon, replacing "Powered by GitHup · Stux.Group"

## v1.0.0

### Added

- A composite GitHub Action, `StuxGroup/GitHup@v1`, with three modes: `check`, `site` and `readme`, running Python 3.12 standard-library scripts with no third-party dependencies
- `.githup.yml` config read by a small, strict YAML subset parser (or `.githup.json`), with validation that rejects unknown keys and unsupported syntax with a line number
- `check`: parallel HTTP probes with retries, expected status codes and ranges, timeouts, methods, request bodies, redirect and TLS options, custom headers with `${{ secrets.NAME }}` / `${NAME}` placeholders, and a `max_response_time` threshold for a degraded state
- Data storage as compact per-monitor, per-month JSON (`data/<slug>/<YYYY-MM>.json`) and `data/summary.json` with current status, last change, uptime for 24 h, 7 d, 30 d, 90 d and all time, and average response times; optional `keep_months` pruning
- Incident Issues labelled `githup`, `incident` and the monitor slug: opened when a monitor goes down, commented on and closed when it recovers
- Data commits as `github-actions[bot]` with messages such as `GitHup: api is down (503)`, rebasing and retrying when a push is rejected
- `site`: a self-contained status page (no external JS or CSS) with an overall banner, 90-day daily history bars with tooltips and keyboard navigation, uptime figures, an inline SVG response-time sparkline, ongoing and recent incidents, light and dark themes with a remembered toggle, live refresh from `summary.json`, the consumer's accent colour, a "Boring Legal Stuff" footer link and "Powered by GitHup · Stux.Group"
- Publishing to the `gh-pages` branch through a temporary worktree, keeping `CNAME` and never touching Pages settings
- `readme`: a status table kept between `<!-- githup:start -->` and `<!-- githup:end -->`
- `templates/githup.yml` consumer workflow (checks every 5 minutes, hourly and on-change site builds, concurrency and permissions) and `examples/.githup.yml`
- Unit tests for the YAML subset parser, config validation, probe classification and retries, uptime maths, data rotation, the site render, the README table, incidents and the full check and deploy flow, plus a CI workflow
- `dev-server.sh`/`dev-server.bat` that build the example site from generated data and serve it locally with `DEV_MODE` on by default (`--no-dev-mode` to opt out)
- `commit.sh`/`commit.bat` release scripts that read `VERSION.md`, tag `vX.Y.Z` and move the floating major tag
