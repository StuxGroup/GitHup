<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo.svg">
    <img src="assets/logo.svg" width="220" height="64" alt="GitHup">
  </picture>
</p>

# GitHup

### *Uptime monitoring and a status page, run entirely on GitHub. [A Stux.Group Service](https://services.stux.group).*

**Website:** [githup.stux.group](https://githup.stux.group) · **Live demo:** [githup.stux.group/demo](https://githup.stux.group/demo/)

Turn any GitHub repository into an uptime monitor with a status page. GitHup is a reusable
GitHub Action: it probes your services from a scheduled workflow, stores the results as JSON in
the repo, opens an Issue when something goes down, and publishes a static status page to GitHub
Pages.

## Overview

- **No servers, no dependencies.** A composite action that runs Python 3.12 standard-library
  scripts. Nothing to install, nothing to vendor.
- **Checks every 5 minutes** with retries, per-monitor expected status codes, timeouts,
  custom headers (with secrets) and a response-time threshold for a *degraded* state.
- **Data in git.** One compact JSON file per monitor per month, plus a `summary.json` with
  current status, uptime for 24 h / 7 d / 30 d / 90 d / all time, and average response times.
- **Incidents as Issues.** A monitor that goes down gets an Issue labelled
  `githup`, `incident` and its slug; GitHup comments and closes it on recovery.
- **A fast, self-contained status page.** Overall banner, 90-day daily history bars with
  tooltips, uptime figures, a response-time sparkline, ongoing and recent incidents, light and
  dark themes, live refresh, keyboard and screen-reader friendly. No external JS or CSS.
- **Groups.** Put related monitors in collapsible sections, each with a combined status.
- **An optional README table** kept up to date between two markers.

## Quick start

1. Create a repository for your status page (public is simplest; see [Pages](#github-pages)).
2. Add `.githup.yml` at its root (start from [`examples/.githup.yml`](examples/.githup.yml)):

   ```yaml
   site:
     name: Example Status
     logo: https://example.com/logo.png
     cname: status.example.com
     accent: "#3ba7ff"
     legal: https://example.com/legal

   monitors:
     - name: Website
       url: https://example.com
     - name: API
       url: https://api.example.com/health
       expected: [200]
       max_response_time: 1000
   ```

3. Copy [`templates/githup.yml`](templates/githup.yml) to `.github/workflows/githup.yml`. It
   checks every 5 minutes (`*/5`), rebuilds the page hourly and whenever a status changes, and
   has the permissions it needs (`contents: write`, `issues: write`) plus a concurrency group so
   data commits never race:

   ```yaml
   jobs:
     check:
       runs-on: ubuntu-latest
       outputs:
         changed: ${{ steps.check.outputs.status-changed }}
       steps:
         - uses: actions/checkout@v7
         - id: check
           uses: StuxGroup/GitHup@v1
           with:
             mode: check
     site:
       needs: check
       # see the template for the full `if:` condition
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v7
           with:
             ref: ${{ github.event.repository.default_branch }}
         - uses: StuxGroup/GitHup@v1
           with:
             mode: readme
         - uses: StuxGroup/GitHup@v1
           with:
             mode: site
   ```

4. Optionally seed an empty `data/summary.json` (`{}`); GitHup creates it on the first run
   otherwise.
5. Run the workflow once from the **Actions** tab (*Run workflow*). The first `site` run creates
   the `gh-pages` branch; then set **Settings → Pages → Source** to *Deploy from a branch*,
   `gh-pages` / `(root)`. GitHup never changes your Pages settings.

## Action inputs

| Input | Default | Used by | Meaning |
| ----- | ------- | ------- | ------- |
| `mode` | (required) | all | `check`, `site` or `readme` |
| `config` | auto | all | Path to the config; default `.githup.yml`, `.githup.yaml` or `.githup.json` |
| `data-dir` | `data` | all | Where the data lives |
| `incidents` | `true` | check, site | Open/close incident Issues; list them on the page |
| `commit` | `true` | check, readme | Commit and push changes as `github-actions[bot]` |
| `deploy` | `true` | site | Push the built page to the Pages branch |
| `pages-branch` | `gh-pages` | site | The branch Pages serves |
| `site-dir` | temp folder | site | Where to build the page (emptied first); see [Deploying with Actions](#deploying-with-actions) |
| `readme` | `README.md` | readme | File with the table markers |
| `site-url` | auto | readme | Status page the table links to; see [A table in another repo](#a-table-in-another-repo) |
| `dry-run` | `false` | all | Change nothing: no writes, commits, Issues or deploys |
| `secrets` | empty | check | JSON for `${{ secrets.NAME }}` placeholders, e.g. `${{ toJSON(secrets) }}` |
| `token` | `github.token` | all | Token for the Issues API |

Outputs of `check`: `status-changed` (`true` when any monitor changed status, and on the first
run), `status` (overall: `up`, `degraded`, `partial`, `down`, `unknown`) and `down` (slugs).
`site` outputs `site-dir`, the folder it built into.

## Config reference

GitHup reads `.githup.yml` with its own small, **strict YAML subset** parser (so there are no
dependencies): block mappings and lists, plain / `'single'` / `"double"` quoted scalars, numbers,
`true`/`false`, `null`, one-line flow lists like `[200, "300-399"]`, and `#` comments. Anchors,
tags, `|`/`>` blocks, multiple documents and duplicate keys are rejected with a line number.
`yes`/`no` stay strings. Quote hex colours, because `#` starts a comment.
Prefer JSON? Use `.githup.json` with the same structure. Unknown keys are errors, so typos
never pass silently.

### `site`

| Key | Default | Meaning |
| --- | ------- | ------- |
| `name` | `Status` | Page title and header |
| `description` | empty | Intro line under the banner |
| `logo` | empty | Logo image URL for the header |
| `favicon` | logo | Favicon URL |
| `cname` | empty | Custom domain, written to `CNAME` on `gh-pages`. If empty, an existing `CNAME` is kept |
| `accent` | `#3ba7ff` | Brand colour (links, sparkline, focus rings); contrast is adjusted per theme automatically |
| `legal` | empty | URL for the footer's **Boring Legal Stuff** link |
| `changelog` | empty | URL of a changelog page. The footer's first link then shows the version (`vX.Y.Z`) and points there |
| `notice` | empty | Text for a **Notice** banner across the top of the page, e.g. planned maintenance |
| `version` | from `VERSION.md` | Version shown on that link; by default read from a `VERSION.md` next to the config file, else the link reads **Changelog** |
| `footer_links` | `[]` | List of `{label, url}` shown in the footer |
| `refresh` | `60` | Seconds between live refreshes of `summary.json` (0 turns it off) |
| `live_data` | `true` | Refresh from the data branch on `raw.githubusercontent.com` (public repos), falling back to the copy on Pages |
| `show_urls` | `true` | Show monitor URLs on the page and in Issues |

The footer always shows **Powered by GitHup v*X.Y.Z* | A Stux.Group Service**, with the version that built the page, muted until hovered. With no `logo` or `favicon`
set, the page uses the GitHup icon as its favicon.

### `monitors`

A list; each entry:

| Key | Default | Meaning |
| --- | ------- | ------- |
| `name` | (required) | Display name |
| `slug` | from name | `a-z`, `0-9`, `-`; names the data folder and the incident label |
| `url` | (required) | `http(s)://` URL to probe |
| `method` | `GET` | `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS` |
| `expected` | `["200-399"]` | Status codes that count as up: numbers, `"200-299"` ranges or `"2xx"` |
| `timeout` | `10` | Seconds per attempt |
| `retries` | `2` | Extra attempts (after `retry_delay` seconds) before it counts as down |
| `retry_delay` | `2` | Seconds between attempts |
| `max_response_time` | none | Milliseconds; slower but otherwise good responses are **degraded** |
| `headers` | none | Mapping (`Authorization: "Bearer ${{ secrets.TOKEN }}"`) or list of `"Name: value"` |
| `body` | none | Request body (for `POST` and friends) |
| `follow_redirects` | `true` | Follow 3xx responses; `false` records the 3xx code itself |
| `verify_tls` | `true` | Verify certificates |
| `description` | empty | Shown under the monitor name |
| `show_url` | `site.show_urls` | Override URL visibility for this monitor |

`defaults:` accepts the same keys (except `name`, `slug`, `url`, `description`, `body`,
`show_url`) and applies them to every monitor, grouped or not. `incidents:` takes `enabled`, `assignees` (a list
of usernames) and extra `labels`. `data:` takes `keep_months` (0 keeps everything).

### `groups`

Put related monitors in their own section. `groups` is a list; each entry takes:

| Key | Default | Meaning |
| --- | ------- | ------- |
| `name` | (required) | Section heading |
| `slug` | from name | `a-z`, `0-9`, `-`; the section's anchor (`#g-<slug>`) |
| `description` | empty | Shown under the heading |
| `collapsed` | `false` | Start the section closed. It still opens itself while one of its monitors is down or degraded |
| `monitors` | (required) | A non-empty list of monitors, with the same keys as `monitors` above |

```yaml
monitors:            # optional: ungrouped monitors, listed first
  - name: Website
    url: https://example.com

groups:
  - name: Platform
    description: The API and documentation behind the product.
    monitors:
      - name: API
        url: https://api.example.com/health
      - name: Docs
        url: https://docs.example.com/
  - name: Assets
    collapsed: true
    monitors:
      - name: CDN
        url: https://cdn.example.com/logo.png
```

You need `monitors`, `groups` or both. Monitor slugs are unique across the whole config, so
moving a monitor into or out of a group keeps its history and incidents. Each group shows a
combined status (*Operational*, *Degraded*, *Partial outage*, *Down*), updated by live refresh,
and the README table gains a **Group** column.

### Secrets in headers and URLs

Placeholders work in `url`, `headers` and `body`:

- `${{ secrets.NAME }}` resolves from the action's `secrets` input
  (`secrets: ${{ toJSON(secrets) }}`), falling back to an environment variable `NAME`.
- `${{ env.NAME }}` and `${NAME}` resolve from environment variables, which you can set on the
  step: `env: { NAME: ${{ secrets.NAME }} }`.

Values passed this way stay masked in logs. A monitor whose placeholder cannot be resolved is
skipped (and the run fails), rather than recorded as an outage.

## How data is stored

```text
data/
  summary.json          current state, uptime windows, all-time totals, open incident
  <slug>/2026-09.json   every check that month, one per line
```

A month file is compact JSON, one check per line so git diffs stay small:

```json
{"monitor":"api","month":"2026-09","fields":["t","status","code","ms"],"checks":[
[1790000000,"up",200,123],
[1790000300,"down",503,88]
]}
```

`t` is a UTC Unix timestamp, `status` is `up`, `degraded` or `down`, `code` is the HTTP status
(`0` when no response arrived) and `ms` the response time. Files rotate by UTC month.

Uptime is check-based: `(up + degraded) / all checks`. Average response times only count checks
that got a good answer. Percentages are rounded down, so 99.999% shows as 99.99%, never 100%.
Daily bars on the page use UTC days. All-time figures come from running totals in
`summary.json`; if that file is lost they are rebuilt from the month files.

Each check commits with a message like `GitHup: api is down (503)` or `GitHup: update data`, as
`github-actions[bot]`.

## README table

`readme` mode writes a status table between `<!-- githup:start -->` and `<!-- githup:end -->`
in your README (or the file set by `readme`), with each monitor's status, uptime and response
time, plus a link to the status page. Configs with groups get a **Group** column.

### A table in another repo

`readme` mode can also keep a table in a README that lives somewhere else, such as an
organisation's `.github` profile: check out the status repo next to it, point `config` and
`data-dir` at that checkout, and set `site-url`, since the status page is not this repo's:

```yaml
- uses: actions/checkout@v7
- uses: actions/checkout@v7
  with:
    repository: example/status
    path: .status
- uses: StuxGroup/GitHup@v1
  with:
    mode: readme
    config: .status/.githup.yml
    data-dir: .status/data
    readme: profile/README.md
    site-url: https://status.example.com/
```

## Incidents

When a monitor is down after all retries, GitHup opens an Issue titled `<Name> is down` with the
labels `githup`, `incident` and the monitor's slug (plus any `incidents.labels`), assigned to
`incidents.assignees`. It is opened once per outage: an open Issue with the same labels is
reused. When the monitor answers again, GitHup comments with the downtime and closes the Issue.
Degraded responses do not open incidents.

The status page lists open incidents at the top and closed ones from the last 90 days, read from
the Issues API at build time. Issues you open yourself with the `githup` and `incident` labels
(add a monitor slug label to link one) appear too, which is handy for planned maintenance.

Set `incidents: "false"` on the action, or `incidents: {enabled: false}` in the config, to turn
this off.

## GitHub Pages

GitHup pushes the built page to `gh-pages` using a temporary worktree, with `.nojekyll` and your
`CNAME`, and never calls the Pages API. Set the Pages source to the `gh-pages` branch once. On a
public repo, live refresh reads `summary.json` straight from the data branch; on a private repo
it falls back to the copy on Pages (updated at each site build).

### Deploying with Actions

To publish with `actions/deploy-pages` instead of a `gh-pages` branch, or to put the status page
in a subfolder of a bigger site, build it into a folder of your own with `deploy: "false"` and
upload that. The page only uses relative links, so it works from any path:

```yaml
- uses: StuxGroup/GitHup@v1
  with:
    mode: site
    deploy: "false"
    site-dir: _site/status      # served at https://example.com/status/
- uses: actions/upload-pages-artifact@v5
  with:
    path: _site
```

Leave `site.cname` empty in that case: with Actions deployments the custom domain lives in the
Pages settings. If you also use `readme` mode, give the job `pages: read` so the table can link
to that domain. [githup.stux.group/demo](https://githup.stux.group/demo/) is built this way.

## Local development

```bash
./dev-server.sh            # or dev-server.bat on Windows; add a port as the last argument
./dev-server.sh --no-dev-mode
python -m unittest discover -s tests -t .
```

`dev-server` generates 90 days of example data for `examples/.githup.yml`, builds the page into
`.dev/site` with `DEV_MODE` on (a dev-only banner) and serves it with `python -m http.server`.
In dev mode, `?banner=soon,maintenance,site` previews the other banner styles.
`--no-dev-mode` renders it exactly as production would.

You can also run any mode by hand from a status repo with `GitHup` on `PYTHONPATH`:

```bash
python -m githup check --dry-run          # probe only, write nothing
python -m githup check --no-commit --no-issues
python -m githup site --no-deploy --out _site
python -m githup readme --dry-run
```

## Versioning

Releases are tagged `vX.Y.Z` and the floating major tag `v1` always points at the newest `1.x.y`
release, so `uses: StuxGroup/GitHup@v1` picks up fixes automatically. `commit.sh`/`commit.bat`
create the release tag and move `v1`; push both with
`git push origin main vX.Y.Z && git push --force origin v1`. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE).

---

*GitHup is [a Stux.Group Service](https://services.stux.group), built & maintained by <img src="https://github.com/StuxGroup.png" height="14" alt="Stux.Group" valign="middle"> [Stux.Group](https://github.com/StuxGroup).  
GitHup is a part of the <img src="https://global.media.stux.group/icon.png" height="14" alt="Stux.Group" valign="middle"> Stux.Group Brand of Companies.*
