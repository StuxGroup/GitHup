@echo off
setlocal
REM GitHup - Git commit + tag script (Windows)
REM Commits whatever's staged/unstaged and tags it with the version
REM currently in VERSION.md, read dynamically so this script never goes
REM stale the way a hardcoded version number does. Also moves the floating
REM major tag (v1 for 1.x.y) to the release, because consumers pin
REM StuxGroup/GitHup@v1.

set "DIR=%~dp0"
set /p VERSION=<"%DIR%VERSION.md"
for /f "tokens=1 delims=." %%a in ("%VERSION%") do set "MAJOR=v%%a"

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

REM Floating major tag: always points at the newest release of this major.
git tag -fa "%MAJOR%" -m "GitHup %MAJOR% (currently v%VERSION%)" "v%VERSION%^{commit}" >nul
echo Moved %MAJOR% to v%VERSION%.

echo Push with: git push origin main v%VERSION% ^&^& git push --force origin %MAJOR%
