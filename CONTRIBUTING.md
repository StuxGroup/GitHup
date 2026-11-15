<p align="center">
  <img src="assets/icon.svg" width="72" height="72" alt="GitHup">
</p>

# Contributing to GitHup

GitHup is [a Stux.Group Service](https://services.stux.group). Issues and pull requests are welcome; this
document explains how to work on it consistently.

## Local setup

No installs are needed beyond Python 3.11+ (the action itself runs 3.12).

```bash
python -m unittest discover -s tests -t .   # run the tests
./dev-server.sh [--no-dev-mode] [--lan] [port]   # or dev-server.bat on Windows
```

`dev-server` generates example data, builds the status page into `.dev/site` with `DEV_MODE`
on and serves it at `http://127.0.0.1:8000`. Add `--lan` to open it from another device on your network
(it prints the addresses to use).

## Project conventions

- **Standard library only.** No third-party packages, ever: the action must run with nothing to
  install. That is why the config uses a home-grown YAML subset parser (`githup/yamlish.py`).
- **The page is self-contained.** No external scripts, stylesheets or fonts; everything is inline
  in `githup/site.py`. Keep colour paired with text, and keep ARIA labels in step with the markup.
  The one exception is the opt-in `site.kat` block, which loads `https://kat.stuxie.dev/kat.js` and adds
  that origin to `script-src` only when it is set; the Privacy and Cookies texts mention it then.
- **Don't promise a check interval.** GitHub runs `schedule:` workflows best-effort, so a `*/5` cron can run
  only a few times a day. Docs and default texts say what the workflow *asks* for and that checks run
  regularly; the page shows the real cadence measured from the data (`summary.json` → `cadence`).
- **Data format is an API.** Consumers' repos hold years of `data/` files. Changes to the month
  files or `summary.json` must stay backwards compatible, or come with a migration and a new channel (`v2`).
- New behaviour needs a test in `tests/`, and a config option needs a row in the README's config
  reference.

- Brand assets live in `assets/` (`icon.svg`, `logo.svg`, `logo-dark.svg`). The status page
  inlines the icon as `GITHUP_ICON` in `githup/site.py`; keep the two in step. `icon.png`
  (512 × 512) and `social-preview.png` (1280 × 640, uploaded under **Settings → General →
  Social preview**) are rendered from the SVGs; re-render them if the SVGs change.

## Branches and going live

- **`main` is what's live.** Nothing is pushed to it directly: it only changes when a pull request from `staging`
  is merged. The floating `v1` tag that status repos use follows `main` (see below).
- **`staging` is the last check before live.** It only changes when a pull request from `test` is merged.
- **Work happens on `test`**, or on a feature branch off `test` that's merged back into it. Releases are made on
  `test` too; `commit.sh` / `commit.bat` refuse to run on `staging` or `main`.
- **Going live:** push `test` with its tag, open a pull request into staging (`gh pr create --base staging --head test`),
  check staging once it's merged, then open one from staging into main (`gh pr create --base main --head staging`).
  CI runs on all three branches and on every pull request. Only Leo merges.

## Versioning and changelog

GitHup uses [Date Versioning](https://datevers.ing): the UTC release date as `YY.MM.DD`, plus `-1`, `-2`...
for later releases the same UTC day. Never a future date.

1. Pick the version: `date -u +%y.%m.%d`, adding `-N` if `git tag -l "v<date>*"` already lists that day.
2. Add a `CHANGELOG.md` entry headed `## vYY.MM.DD` with `###` subsections in this order: Added,
   Changed, Fixed, Removed, Security, Deprecated. Never a bare bullet list under a version.
3. Set `VERSION.md` (the bare version, no `v`) and `githup/__init__.py` to it; a test checks they match
   and that the changelog's newest heading is the same version.
4. Update the README if relevant, then run `commit.sh` (bash) or `commit.bat` (Windows). They read
   `VERSION.md`, refuse to run on `staging` or `main`, reject anything that is not a real, non-future Date
   Version, commit and create the annotated `vYY.MM.DD` tag. They print the commands for the next steps. No
   need to edit them per release.
5. Push the release and open a pull request into `staging`; once staging is checked and merged, open one from
   `staging` into `main`:

   ```bash
   git push origin test --tags
   gh pr create --base staging --head test
   gh pr create --base main --head staging   # after the first one is merged
   ```

6. Once the pull request into `main` is merged, move the channel, so `@v1` users only ever get live releases:

   ```bash
   git fetch origin
   git tag -fa v1 -m "GitHup v1 (currently vYY.MM.DD)" "vYY.MM.DD^{commit}"
   git push --force origin v1     # consumers use StuxGroup/GitHup@v1
   ```

   Only force-push `v1`, never a `vYY.MM.DD` tag. `v1` is a compatibility channel: a breaking change starts
   `v2` and leaves `v1` where it is.
