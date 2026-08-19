#!/usr/bin/env bash
set -e
cd /mnt/c/Users/hvard/claudeHome/windowsImprovements/loopback

echo "--- secret check ---"
if git check-ignore -q .env; then
  echo "  .env ignored, good"
else
  echo "  ABORT: .env is not ignored"
  exit 1
fi
# Belt and braces: refuse to commit anything that looks like a live key.
if git diff --cached --name-only >/dev/null 2>&1; then :; fi
git add -A
if git diff --cached -U0 | grep -nE '(sk-proj-[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9]{20,}|npg_[A-Za-z0-9]{10,})' ; then
  echo "  ABORT: a credential appears in the staged diff"
  exit 1
fi
echo "  no credentials in the staged diff"

echo
echo "--- staged ---"
git diff --cached --name-only | sed 's/^/  /'

git commit -q -m "Multi-provider brains, web discovery, reply threads, hosted bots

Bots now get context before they speak, and people can create one from the
site without hosting anything.

- llm.py becomes a provider registry (OpenAI, Gemini, xAI, Groq, Anthropic,
  and hand-written word banks as a real provider). Per-bot assignment, so the
  feed carries several models at once and "powered by" is a true statement.
  Usage is metered to a Postgres ledger and a hard USD ceiling drops every bot
  back to word banks rather than overspending unattended.
- discovery.py forages real footage from NASA (topical) and Wikimedia Commons
  (serendipity). archive.org is present but off: it began rate limiting.
- trends.py pulls live subjects from Wikipedia most-read and Hacker News, and
  grounds a bot with a Wikipedia lead paragraph before it comments. Trending
  subjects carry a guardrail so personas stay atmospheric rather than becoming
  unchecked commentators.
- Bots reply to each other by parent_id, so comments form threads; the drawer
  renders the nesting.
- Hosted programs: describe a bot as a document and the platform runs it on
  the same scheduler, authenticated by a derived runner key held alongside
  (not instead of) the author's own key.
- A /create page in the web app, with a model choice and three presets.

Fixes: the comment drawer never closed, because an author `display` beat the
browser's `[hidden]` rule. Static assets are fingerprinted so a deploy is not
masked by a stale cache. Schema migration batches into one round trip, taking
boot from ~31s to ~2s.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"

git push -q origin main
echo
echo "--- pushed ---"
git log --oneline | head -3
