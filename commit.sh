#!/bin/bash
# GitHup - Git commit + tag script
# Commits whatever's staged/unstaged and tags it with the version currently
# in VERSION.md, read dynamically so this script never goes stale the way a
# hardcoded version number does. Also moves the floating major tag (v1 for
# 1.x.y) to the release, because consumers pin `StuxGroup/GitHup@v1`.
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(tr -d '[:space:]' < "$DIR/VERSION.md")"
MAJOR="v${VERSION%%.*}"

git add -A
if ! git diff --cached --quiet; then
    git commit -m "$(cat <<EOF
Release v${VERSION}

See CHANGELOG.md for details.
EOF
)"
else
    echo "Nothing to commit - tagging the current HEAD as v${VERSION}."
fi

if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    echo "Tag v${VERSION} already exists - skipping."
else
    git tag -a "v${VERSION}" -m "GitHup v${VERSION}"
    echo "Tagged v${VERSION}."
fi

# Floating major tag: always points at the newest release of this major.
git tag -fa "${MAJOR}" -m "GitHup ${MAJOR} (currently v${VERSION})" "v${VERSION}^{commit}" >/dev/null
echo "Moved ${MAJOR} to v${VERSION}."

echo "Push with: git push origin main v${VERSION} && git push --force origin ${MAJOR}"
