#!/usr/bin/env bash
set -e
cd /mnt/c/Users/hvard/claudeHome/windowsImprovements/loopback

echo "--- secret check ---"
git check-ignore -q .env || { echo "  ABORT: .env is not ignored"; exit 1; }
echo "  .env ignored, good"
git add -A
if git diff --cached -U0 | grep -nE '(sk-proj-[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9]{20,}|npg_[A-Za-z0-9]{10,}|AIzaSy[A-Za-z0-9_-]{20,})'; then
  echo "  ABORT: a credential appears in the staged diff"
  exit 1
fi
echo "  no credentials in the staged diff"

echo
git diff --cached --name-only | sed 's/^/  /'

git commit -q -F - <<'MSG'
Commenters argue with each other in the replies

The archetypes could each leave one comment on a clip and that was the whole
section: thirteen people talking past each other, capped at thirteen because
there are thirteen archetypes. A comment section does not go viral in the
top-level comments, it goes viral in the replies.

- archetypes gain a reply register, kept separate from the persona: people
  write differently at each other than they do at a video.
- commenters.comment_war() opens with a spread of arrivals, then spends the
  rest of its budget on replies, and lets a reply itself be replied to so
  threads go deep instead of staying two levels.
- FRICTION maps who will actually clash. @the_receipts corrects
  @fun_fact_actually, @no_hesitation deflates @under_a_limit's moralising.
  Left to a random pairing the two would sometimes simply agree, which is not
  an argument.
- Existing comments seed the roots, so a second wave argues with the first
  rather than forming a separate section stacked on the same post.
- run_comment_war.py, scoped to real YouTube footage.

Three things the dry run caught. A bot addressed itself, having inferred its
target from a transcript ending in its own line -- the reply prompt now names
the target and forbids self-address. @fun_fact_actually answered one comment
twice with the same fact about sword durability, so a pairing is now used
once. And some replies came back as a bare handle, or a handle plus three
words echoing the parent; those are withheld rather than published, because
visible filler is worse than a shorter thread.

The bots may be scathing to each other. The guards against slurs, cruelty and
anything aimed at a real person apply to every line, including the angry ones.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG

git push -q origin main
echo
echo "--- pushed ---"
git log --oneline | head -3
