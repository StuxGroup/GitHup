# Changelog

All notable changes to GitHup are documented here. GitHup follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); the floating `v1` tag always points
at the newest 1.x.y release.

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
