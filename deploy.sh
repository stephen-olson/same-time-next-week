#!/usr/bin/env bash
# Publish the site to GitHub Pages, served from the docs/ folder of the main branch.
# Needs a GitHub login first:  gh auth login -h github.com
# Usage: ./deploy.sh [repo-name]     (default: same-time-next-week)
set -euo pipefail
REPO="${1:-same-time-next-week}"
cd "$(dirname "$0")"

gh auth status >/dev/null
OWNER="$(gh api user --jq .login)"
SITE_URL="https://${OWNER}.github.io/${REPO}/"

python3 -I build.py --site-url "$SITE_URL"

[ -d .git ] || git init -b main
git add -A
git commit -m "Publish Same Time Next Week" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" || true

if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  gh repo create "$REPO" --public --source . --remote origin --description "Things to do with people in Durham and Raleigh, NC"
fi
# Use the gh login for this push only, without changing global git settings.
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -u origin main

# Turn on GitHub Pages from main:/docs (create, or update if it already exists).
gh api -X POST "repos/$OWNER/$REPO/pages" -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 \
  || gh api -X PUT "repos/$OWNER/$REPO/pages" -f "source[branch]=main" -f "source[path]=/docs" >/dev/null

echo "Published. The site will be live in a minute or two at: $SITE_URL"
