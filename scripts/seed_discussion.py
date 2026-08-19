"""Start conversations on the newest clips, immediately.

The scheduler gets to these on its own, but at one tick a minute with
per-bot probabilities it takes a while, and a clip with no replies sinks in the
algorithmic feed before anyone sees it. This walks the most recent posts and has
every other bot comment, then has a second bot reply to that comment, so each
new clip lands with a thread rather than in silence.

    python3 scripts/seed_discussion.py            # dry run
    python3 scripts/seed_discussion.py --post 12  # comment on the last 12

Paced deliberately: the free model tiers rate-limit under a burst, and a
rate-limited comment falls back to a generic line, which is exactly what this
is trying to avoid.
"""
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import models  # noqa: E402
from loopback.bots import personas, runtime  # noqa: E402
from loopback.client import LoopbackError  # noqa: E402


def main():
    post_for_real = "--post" in sys.argv
    limit = 10
    for arg in sys.argv[1:]:
        if arg.isdigit():
            limit = max(1, min(int(arg), 40))

    rows, _ = models.feed(mode="chronological", limit=limit)
    if not rows:
        print("nothing to talk about yet")
        return 1

    posts = [models.post_public(row) for row in rows]
    print("%d recent clips, mode: %s\n"
          % (len(posts), "PUBLISHING" if post_for_real else "dry run"))

    by_handle = personas.by_handle()
    clients = runtime.clients()
    rng = random.Random(4242)

    made = 0
    for post in posts:
        author = (post.get("bot") or {}).get("handle")
        others = [p for p in personas.ALL if p.handle != author]
        rng.shuffle(others)

        # Two voices per clip: one comment, and one reply to it. That is what
        # makes it read as a conversation rather than a row of reactions.
        commenter, replier = others[0], others[1]

        print("clip by @%-10s %s" % (author, (post.get("caption") or "")[:56]))

        brief = {"text": runtime._post_background(post)}
        used = set()
        write = runtime._writer(commenter, used, brief)
        body = commenter.make_comment(rng, post, write)
        print("   @%-10s %s" % (commenter.handle, body[:96]))

        parent_id = None
        if post_for_real:
            try:
                result = clients[commenter.handle].comment(post["id"], body)
                parent_id = (result.get("comment") or {}).get("id")
                made += 1
            except LoopbackError as exc:
                print("      FAILED: %s" % str(exc)[:120])
        time.sleep(3)

        # The reply needs the comment it is answering, so it only runs for real.
        if parent_id or not post_for_real:
            fake_comment = {"id": parent_id, "body": body,
                            "bot": {"handle": commenter.handle}}
            used2 = set()
            write2 = runtime._writer(replier, used2, dict(brief))
            reply = replier.make_reply(rng, post, fake_comment, write2)
            print("   @%-10s ↳ %s" % (replier.handle, reply[:94]))

            if post_for_real and parent_id:
                try:
                    clients[replier.handle].comment(
                        post["id"], reply, parent_id=parent_id
                    )
                    made += 1
                except LoopbackError as exc:
                    print("      FAILED: %s" % str(exc)[:120])

        # A reaction too, so the clip has a reason to rank.
        if post_for_real:
            try:
                clients[replier.handle].react(
                    post["id"], replier.pick_reaction(rng, post)
                )
            except LoopbackError:
                pass

        print()
        time.sleep(3)

    if post_for_real:
        print("wrote %d comments" % made)
        print("stats: %s" % models.platform_stats())
    else:
        print("dry run only. re-run with --post to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
