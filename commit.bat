@echo off
setlocal
REM GitHup - Git commit + tag script (Windows)
REM Commits whatever's staged/unstaged and tags it with the version
REM currently in VERSION.md, read dynamically so this script never goes
REM stale the way a hardcoded version number does. Also moves the floating
REM tag v1 to the release, because consumers pin StuxGroup/GitHup@v1.
REM GitHup uses Date Versioning, so v1 is a compatibility channel, not a
REM version's major number: it keeps following the newest release until a
REM breaking change starts a new channel (change CHANNEL below then).

set "DIR=%~dp0"
set /p VERSION=<"%DIR%VERSION.md"
set "CHANNEL=v1"

REM Date Versioning (https://datevers.ing): the UTC release date as YY.MM.DD, plus -1, -2... for later releases that day
powershell -NoProfile -Command "$v = '%VERSION%'.Trim(); if ($v -notmatch '^\d{2}\.(0[1-9]|1[0-2])\.(0[1-9]|[12]\d|3[01])(-[1-9]\d*)?$') { exit 1 }; $d = $v.Split('-')[0]; $p = [DateTime]::MinValue; if (-not [DateTime]::TryParseExact($d, 'yy.MM.dd', [Globalization.CultureInfo]::InvariantCulture, 'None', [ref]$p)) { exit 1 }; $t = [DateTime]::UtcNow.ToString('yy.MM.dd'); if ($d -gt $t) { exit 2 }; if ($d -lt $t) { exit 3 }; exit 0"
if errorlevel 3 (
    echo Warning: VERSION.md is dated before today ^(UTC^). Releasing today? Use today's date.
) else if errorlevel 2 (
    echo VERSION.md holds %VERSION%, which is dated in the future ^(UTC^). Date Versions can't be.
    exit /b 1
) else if errorlevel 1 (
    echo VERSION.md holds %VERSION%, which isn't a Date Version ^(YY.MM.DD or YY.MM.DD-N, see https://datevers.ing^).
    exit /b 1
)

git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Release v%VERSION%" -m "See CHANGELOG.md for details."
) else (
    echo Nothing to commit - tagging the current HEAD as v%VERSION%.
)

git rev-parse "v%VERSION%" >nul 2>&1
if errorlevel 1 (
    git tag -a "v%VERSION%" -m "GitHup v%VERSION%"
    echo Tagged v%VERSION%.
) else (
    echo Tag v%VERSION% already exists - skipping.
)

REM Floating channel tag: always points at the newest release.
git tag -fa "%CHANNEL%" -m "GitHup %CHANNEL% (currently v%VERSION%)" "v%VERSION%^{commit}" >nul
echo Moved %CHANNEL% to v%VERSION%.

echo Push with: git push origin main v%VERSION% ^&^& git push --force origin %CHANNEL%
