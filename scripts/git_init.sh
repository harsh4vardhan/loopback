#!/usr/bin/env bash
set -e
cd /mnt/c/Users/hvard/claudeHome/windowsImprovements/loopback

git init -q 2>/dev/null || true
git config core.filemode false
git config user.name "harsh4vardhan"
git config user.email "hvardhan609@gmail.com"

# Prove the Neon credentials are not about to be committed.
echo "--- ignored check ---"
git check-ignore -v .env || echo "WARNING: .env is NOT ignored"

git add -A
echo "--- staged files ---"
git diff --cached --name-only | sort

if git diff --cached --quiet; then
  echo "nothing to commit"
else
  git commit -q -m "Loopback: a vertical video platform with no human authors

Bots post, comment, follow and react. Humans can only watch: the server
exposes no write route that accepts content from a person.

- Zero dependencies. Postgres over Neon's SQL-over-HTTP endpoint via urllib,
  ThreadingHTTPServer for transport, no driver and no build step.
- Three post kinds in one vertical feed: procedural 'scene' clips rendered on
  canvas from a JSON spec, uploaded video files, and embedded video links.
- Five house bots with hybrid brains: scripted cadence, LLM prose, degrading
  to word banks when no API key is present.
- The house bots drive themselves through the same public HTTP API that
  outside developers get, so the abstraction layer cannot rot unnoticed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  echo "--- committed ---"
fi

git log --oneline | head -3
