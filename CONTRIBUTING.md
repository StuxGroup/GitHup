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
  files or `summary.json` must stay backwards compatible, or come with a migration and a major
  version.
- New behaviour needs a test in `tests/`, and a config option needs a row in the README's config
  reference.

- Brand assets live in `assets/` (`icon.svg`, `logo.svg`, `logo-dark.svg`). The status page
  inlines the icon as `GITHUP_ICON` in `githup/site.py`; keep the two in step. `icon.png`
  (512 × 512) and `social-preview.png` (1280 × 640, uploaded under **Settings → General →
  Social preview**) are rendered from the SVGs; re-render them if the SVGs change.

## Versioning and changelog

- The version lives in `VERSION.md` (a bare version string) and in `githup/__init__.py`; bump
  both on every release (a test checks they match).
- Every release gets a `CHANGELOG.md` entry using `###` subsections in this order: Added,
  Changed, Fixed, Removed, Security, Deprecated. Never a bare bullet list under a version.
- `commit.sh` (bash) and `commit.bat` (Windows) read `VERSION.md`, commit, create the annotated
  `vX.Y.Z` tag and move the floating major tag (`v1`) to it. No need to edit them per release.
- Push a release with:

  ```bash
  git push origin main vX.Y.Z
  git push --force origin v1     # consumers use StuxGroup/GitHup@v1
  ```

  Only force-push the major tag, never a `vX.Y.Z` tag. A breaking change means a new major
  (`v2`), leaving `v1` where it is.
