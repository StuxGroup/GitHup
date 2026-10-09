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
- **Groups.** Put related monitors in collapsible sections, each with a combined status, plus plain link sections without monitoring.
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

## Schedule delays

GitHub runs `schedule:` workflows on a best-effort basis. A `*/5` cron is often late and can be
skipped under load; on our own status repos it sometimes ran only every 1 to 5 hours. While that
happens, the status page shows stale results, and GitHup logs a `::warning::` such as "The last
check was 2 h 14 min ago: GitHub delayed this scheduled run".

The opt-in **`fill-gaps`** input (off by default) makes a late run catch up. It is adaptive:

- If the last check is less than 1.5 × `repeat-interval` old, the schedule is working and the run
  does exactly one check, the same as without the option. A healthy schedule costs the same as
  before.
- If the last check is overdue (or there is none yet), the run checks up to `repeat` times (at
  most 6), `repeat-interval` seconds apart (at least 60, default 300). Each check is a full round:
  probe, record, commit and push, open and close incident Issues. Before every extra round GitHup
  looks again and stops early when a newer check has landed in the meantime.

This is not a 24/7 loop: it only fills a gap, once, per delayed run. With `fill-gaps` off, `repeat`
and `repeat-interval` are ignored (GitHup logs a notice saying so).

```yaml
- id: check
  uses: StuxGroup/GitHup@v1
  with:
    mode: check
    fill-gaps: "true"
    repeat: 4
    repeat-interval: 300
```

Also set the job's `timeout-minutes` above `(repeat - 1) × repeat-interval` plus the check time
(25 fits the values above) and keep a `concurrency` group with `cancel-in-progress: false`, so a
late run that overlaps a running one queues instead of racing.

### Risks of enabling it

- GitHub's [terms for Actions](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#actions)
  say Actions should not be used for serverless computing or for activity unrelated to the
  repository's software project. Uptime monitoring on Actions is a grey area for every tool that
  does it, and longer runs increase your footprint. GitHup's adaptive design keeps a healthy
  schedule's cost unchanged, but GitHub could still restrict Actions on repositories that use it.
- Minutes: a gap-filling run lasts about `(repeat - 1) × repeat-interval` plus the check time, so
  roughly 16 minutes with the values above instead of about one. Public repositories do not pay
  for Actions minutes. On private repositories that is roughly 15 extra minutes of your monthly
  allowance for every delayed run, and a day of constant delays can use several hours.

## Action inputs

| Input | Default | Used by | Meaning |
| ----- | ------- | ------- | ------- |
| `mode` | (required) | all | `check`, `site` or `readme` |
| `config` | auto | all | Path to the config; default `.githup.yml`, `.githup.yaml` or `.githup.json` |
| `data-dir` | `data` | all | Where the data lives |
| `incidents` | `true` | check, site | Open/close incident Issues; list them on the page |
| `fill-gaps` | `false` | check | Off by default. When the last check is overdue, check up to `repeat` times in this run; see [Schedule delays](#schedule-delays) for the risks |
| `repeat` | `1` | check | Checks in a gap-filling run, 1 to 6. Only used with `fill-gaps: "true"` |
| `repeat-interval` | `300` | check | Seconds between those checks, at least 60. Only used with `fill-gaps: "true"` |
| `commit` | `true` | check, readme | Commit and push changes as `github-actions[bot]` |
| `deploy` | `true` | site | Push the built page to the Pages branch |
| `pages-branch` | `gh-pages` | site | The branch Pages serves |
| `site-dir` | temp folder | site | Where to build the page (emptied first); see [Deploying with Actions](#deploying-with-actions) |
| `readme` | `README.md` | readme | File with the table markers |
| `site-url` | auto | readme | Status page the table links to; see [A table in another repo](#a-table-in-another-repo) |
| `dry-run` | `false` | all | Change nothing: no writes, commits, Issues or deploys |
| `secrets` | empty | check | JSON for `${{ secrets.NAME }}` placeholders, e.g. `${{ toJSON(secrets) }}` |
| `token` | `github.token` | all | Token for the Issues API |

Outputs of `check`: `status-changed` (`true` when any monitor changed status in any round, and on
the first run), `status` (overall: `up`, `degraded`, `partial`, `down`, `unknown`) and `down`
(slugs); both reflect the last round.
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
| `url` | empty | Canonical base URL, used for the sitemap when there is no `cname` (e.g. `https://owner.github.io/repo/`) |
| `legal` | empty | URL for the footer's **Boring Legal Stuff** link. Ignored when the [`legal` block](#legal) is set |
| `notice` | empty | Text for a **Notice** banner across the top of the page, e.g. planned maintenance |
| `footer_links` | `[]` | List of `{label, url}` shown in the footer |
| `refresh` | `60` | Seconds between live refreshes of `summary.json` (0 turns it off) |
| `live_data` | `true` | Refresh from the data branch on `raw.githubusercontent.com` (public repos), falling back to the copy on Pages |
| `show_urls` | `true` | Show monitor URLs on the page and in Issues |
| `copyright` | none | Optional [copyright line](#sitecopyright) in the footer: `holder` and the project's `start` year |
| `changelog` | | **Deprecated.** Accepted but ignored, with a warning in the log |
| `version` | | **Deprecated.** Accepted but ignored, with a warning in the log |

The footer shows **Powered by GitHup v*X.Y.Z* | A Stux.Group Service**, with the version that built the
page, muted until hovered. The version links to the
[GitHup changelog](https://githup.stux.group/changelogs/#githup); it is the only version on the page.
With no `logo` or `favicon` set, the page uses the GitHup icon as its favicon.

#### `site.copyright`

An optional block that adds a copyright line to the footer of every generated page (status page,
legal pages, 404 and sitemap):

```yaml
site:
  copyright:
    holder: Example Ltd   # required: who owns the copyright
    start: 2024           # optional: the year the project started
```

| Key | Default | Meaning |
| --- | ------- | ------- |
| `holder` | required | The copyright holder, shown as written |
| `start` | none | Four-digit year the project started (1900-2999) |

The footer then reads **Copyright &copy; 2024–2026 Example Ltd**: just the year in the start year itself
(or when `start` is left out), and `START–CURRENT` (with an en dash) after that. The current year is the
year of the build, in UTC. Status pages are rebuilt at least hourly, so the line rolls over on 1 January
without any edit. Without the block no copyright line is shown. Unknown keys and a malformed `start` are config errors.

### `legal`

An optional block. When set, `site` mode also generates, in the page's own theme (light and dark,
banner, footer), a legal hub at `/legal/` and six sub-pages: `/legal/privacy/`, `/legal/terms/`,
`/legal/cookies/`, `/legal/imprint/`, `/legal/disclaimer/` and `/legal/opt-out/`. The default texts
describe a status page: no accounts, no personal data, no cookies, data from GitHub, hosted on
GitHub Pages. The footer's **Boring Legal Stuff** link points at `/legal/`. If you also set
`site.legal` (a URL), the generated pages win. With only `site.legal`, the link goes there as before.

| Key | Default | Meaning |
| --- | ------- | ------- |
| `operator` | the site name | Name shown as the operator of the page |
| `company` | empty | Free-text legal entity line for the Imprint: name, number, registered office |
| `contact` | empty | Contact email. Without one, the texts point to the repo's Issues |
| `host` | `GitHub Pages` | Where the page is hosted |
| `effective` | empty | Date shown on every legal page |

```yaml
legal:
  operator: Example Ltd
  company: "Example Ltd, a company registered in England and Wales (no. 01234567), registered office 1 High Street, London, AB1 2CD."
  contact: legal@example.com
  effective: 1 October 2026
```

### Other generated pages

`site` mode also writes a themed `404.html` (header, banner, footer and a link home). When a base URL
is known (`site.cname`, else `site.url`) it writes `sitemap.xml` (the status page and, when generated,
the legal pages), a `robots.txt` with a `Sitemap:` line, and a `/sitemap/` page listing them; the footer
then gets a **Sitemap** link. Without either key, the sitemap is skipped and the log says so. An existing
`robots.txt` in the output directory is kept as it is. All pages are self-contained (inline CSS) and use
relative links, so they work in subfolders.

### `monitors`

A list; each entry:

| Key | Default | Meaning |
| --- | ------- | ------- |
| `name` | (required) | Display name |
| `slug` | from name | `a-z`, `0-9`, `-`; names the data folder and the incident label |
| `url` | (required) | `http(s)://` URL to probe |
| `method` | `GET` | `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS` |
| `expected` | `["200-399"]` | Status codes that count as up: numbers, `"200-299"` ranges or `"2xx"` |
| `timeout` | `15` | Seconds per attempt |
| `retries` | `2` | Extra attempts (after `retry_delay` seconds) before it counts as down |
| `retry_delay` | `2` | Seconds between attempts |
| `max_response_time` | `15000` | Milliseconds; slower but otherwise good responses are **degraded**. `0` or `false` turns it off |
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
| `monitors` | (see below) | A list of monitors, with the same keys as `monitors` above |
| `links` | (see below) | A list of plain links: `name` and `url` (http/https) are required, `description` is optional |

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
  - name: Related
    links:             # plain links: no status checks
      - name: Example Blog
        url: https://blog.example.com
        description: News and release notes
```

A group needs at least one monitor or one link, and may have both. You need `monitors`, `groups` or both. Monitor slugs are unique across the whole config, so
moving a monitor into or out of a group keeps its history and incidents. Each group shows a
combined status (*Operational*, *Degraded*, *Partial outage*, *Down*), updated by live refresh,
and the README table gains a **Group** column.

**Links.** A `links` entry is just a link, for sections like "Related" that point at other sites without
monitoring them. Links are never probed and have no data folders, incidents, uptime or summary entries, and
they do not count towards the overall status. They show as simple link cards (name, URL and description)
inside the group's section. A group with only links has no status pill; `collapsed` works as usual. Links are
left out of the `readme` table and the sitemap. Unknown keys inside a link are errors, like everywhere else.

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

### Blocked runners

GitHub Actions runners share IP addresses, and a CDN or host sometimes refuses one outright. When
most monitors in a round (more than half, and at least two) fail with the same blocking status
code (401, 403, 407 or 429), GitHup treats the round as inconclusive: those results are not
recorded, no incidents open, every status stays as it was, and the run logs a warning naming the
monitors. Real outages (5xx responses, timeouts, refused connections) always count. A monitor that
keeps being refused counts as down once its last recorded check is more than 6 hours old, so a
site that really does start refusing everyone still shows up.

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
Pages settings. Set `site.url` (here `https://example.com/status/`) to get the sitemap. If you also use `readme` mode, give the job `pages: read` so the table can link
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
GitHup is a part of the <picture><source media="(prefers-color-scheme: dark)" srcset="https://global.media.stux.group/icon-light.png"><source media="(prefers-color-scheme: light)" srcset="https://global.media.stux.group/icon-dark.png"><img src="https://global.media.stux.group/icon-dark.png" height="14" alt="Stux.Group" valign="middle"></picture> Stux.Group Brand of Companies.*
