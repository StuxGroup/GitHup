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
./dev-server.sh [--no-dev-mode] [port]      # or dev-server.bat on Windows
```

`dev-server` generates example data, builds the status page into `.dev/site` with `DEV_MODE`
on and serves it at `http://127.0.0.1:8000`.

## Project conventions

- **Standard library only.** No third-party packages, ever: the action must run with nothing to
  install. That is why the config uses a home-grown YAML subset parser (`githup/yamlish.py`).
- **The page is self-contained.** No external scripts, stylesheets or fonts; everything is inline
  in `githup/site.py`. Keep colour paired with text, and keep ARIA labels in step with the markup.
- **Data format is an API.** Consumers' repos hold years of `data/` files. Changes to the month
  files or `summary.json` must stay backwards compatible, or come with a migration and a new channel (`v2`).
- New behaviour needs a test in `tests/`, and a config option needs a row in the README's config
  reference.

- Brand assets live in `assets/` (`icon.svg`, `logo.svg`, `logo-dark.svg`). The status page
  inlines the icon as `GITHUP_ICON` in `githup/site.py`; keep the two in step. `icon.png`
  (512 × 512) and `social-preview.png` (1280 × 640, uploaded under **Settings → General →
  Social preview**) are rendered from the SVGs; re-render them if the SVGs change.

## Versioning and changelog

GitHup uses [Date Versioning](https://datevers.ing): the UTC release date as `YY.MM.DD`, plus `-1`, `-2`...
for later releases the same UTC day. Never a future date.

1. Pick the version: `date -u +%y.%m.%d`, adding `-N` if `git tag -l "v<date>*"` already lists that day.
2. Add a `CHANGELOG.md` entry headed `## vYY.MM.DD` with `###` subsections in this order: Added,
   Changed, Fixed, Removed, Security, Deprecated. Never a bare bullet list under a version.
3. Set `VERSION.md` (the bare version, no `v`) and `githup/__init__.py` to it; a test checks they match
   and that the changelog's newest heading is the same version.
4. Update the README if relevant, then run `commit.sh` (bash) or `commit.bat` (Windows). They read
   `VERSION.md`, reject anything that is not a real, non-future Date Version, commit, create the annotated
   `vYY.MM.DD` tag and move the floating `v1` tag to it. No need to edit them per release.
5. Push the release to `test` and open a pull request into `main`:

   ```bash
   git push origin test vYY.MM.DD
   ```

6. Once the pull request is merged, move the channel, so `@v1` users only ever get reviewed releases:

   ```bash
   git push --force origin v1     # consumers use StuxGroup/GitHup@v1
   ```

   Only force-push `v1`, never a `vYY.MM.DD` tag. `v1` is a compatibility channel: a breaking change starts
   `v2` and leaves `v1` where it is.

Work happens on `test` (or a branch off it), never on `main`. Changes reach `main` only through a pull request from `test`; the release commit and tag are made on `test` and go live when the pull request is merged.
