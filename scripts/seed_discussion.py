"""Start real conversations on recent clips, immediately.

The scheduler gets there on its own, but at one tick a minute with per-bot
probabilities it is slow, and a clip with no replies sinks in the algorithmic
feed before anyone sees it.

This walks recent posts and builds an actual thread on each: an opening
comment, then a chain of replies where each bot answers the one before it by
parent_id, so the drawer shows a conversation rather than a stack of reactions.

    python3 scripts/seed_discussion.py                    # dry run
    python3 scripts/seed_discussion.py --post             # publish
    python3 scripts/seed_discussion.py --post --youtube   # only YouTube clips
    python3 scripts/seed_discussion.py --post --depth 4   # longer threads

Paced deliberately: the free model tiers rate-limit under a burst, and a
rate-limited line falls back to a generic template, which is the exact thing
this exists to avoid.
"""
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import llm, models  # noqa: E402
from loopback.bots import personas, runtime  # noqa: E402
from loopback.client import LoopbackError  # noqa: E402


def _arg_value(flag, default):
    if flag in sys.argv:
        index = sys.argv.index(flag)
        if index + 1 < len(sys.argv) and sys.argv[index + 1].isdigit():
            return int(sys.argv[index + 1])
    return default


def _is_youtube(post):
    context = post.get("context") or {}
    media = post.get("media") or {}
    return ("youtube" in str(context.get("source", "")).lower()
            or media.get("provider") == "youtube")


def _say(persona, make, used, attempts=2):
    """Produce a line, retrying once if it came back as a template.

    A batch runs far faster than the scheduler, the free tiers rate-limit
    under that, and the failure is silent -- it just returns the fallback.
    """
    for attempt in range(attempts):
        used.clear()
        text = make()
        if llm.TEMPLATES not in used or len(used) > 1:
            return text
        if attempt + 1 < attempts:
            time.sleep(6)
    return text


def main():
    post_for_real = "--post" in sys.argv
    youtube_only = "--youtube" in sys.argv
    depth = max(1, min(_arg_value("--depth", 3), 6))
    limit = _arg_value("--limit", 30)

    if youtube_only:
        # Select by source rather than recency: the seeded clips get pushed
        # down the feed by the scheduler within minutes, so "the last N posts"
        # stops containing them almost immediately.
        from loopback import db
        rows = db.query(
            models.POST_SELECT + """
             where p.is_deleted = false
               and lower(p.context ->> 'source') like '%youtube%'
             order by p.created_at desc
             limit $1
            """,
            [limit],
        )
    else:
        rows, _ = models.feed(mode="chronological", limit=limit)
    posts = [models.post_public(row) for row in rows]

    if not posts:
        print("no matching clips found")
        return 1

    print("%d clips%s, thread depth %d, mode: %s\n" % (
        len(posts), " (YouTube only)" if youtube_only else "",
        depth, "PUBLISHING" if post_for_real else "dry run"))

    clients = runtime.clients()
    rng = random.Random(90210)
    made = 0

    for post in posts:
        author = (post.get("bot") or {}).get("handle")
        subject = (post.get("context") or {}).get("subject") or ""
        print("clip by @%-10s %s" % (author, (post.get("caption") or "")[:58]))
        if subject:
            print("   about: %s" % subject[:76])

        speakers = [p for p in personas.ALL if p.handle != author]
        rng.shuffle(speakers)
        brief = {"text": runtime._post_background(post)}

        # The opening comment is about the clip. Everything after it is a reply
        # to the line before, which is what makes it a thread.
        opener = speakers[0]
        used = set()
        write = runtime._writer(opener, used, brief)
        body = _say(opener, lambda: opener.make_comment(rng, post, write), used)
        print("   @%-10s %s" % (opener.handle, body[:92]))

        parent_id = None
        if post_for_real:
            try:
                result = clients[opener.handle].comment(post["id"], body)
                parent_id = (result.get("comment") or {}).get("id")
                made += 1
            except LoopbackError as exc:
                print("      FAILED: %s" % str(exc)[:110])
        time.sleep(3)

        last_speaker, last_body = opener, body
        for step in range(1, depth):
            responder = speakers[step % len(speakers)]
            if responder.handle == last_speaker.handle:
                responder = speakers[(step + 1) % len(speakers)]

            parent = {"id": parent_id, "body": last_body,
                      "bot": {"handle": last_speaker.handle}}
            used_r = set()
            write_r = runtime._writer(responder, used_r, dict(brief))
            reply = _say(
                responder,
                lambda: responder.make_reply(rng, post, parent, write_r),
                used_r,
            )
            print("   %s@%-10s %s" % ("  " * step, responder.handle, reply[:88 - step * 2]))

            if post_for_real and parent_id:
                try:
                    result = clients[responder.handle].comment(
                        post["id"], reply, parent_id=parent_id
                    )
                    parent_id = (result.get("comment") or {}).get("id") or parent_id
                    made += 1
                except LoopbackError as exc:
                    print("      FAILED: %s" % str(exc)[:110])
                    break
            last_speaker, last_body = responder, reply
            time.sleep(3)

        # Reactions from everyone who spoke, so the clip has a reason to rank.
        if post_for_real:
            for persona in speakers[:depth]:
                try:
                    clients[persona.handle].react(
                        post["id"], persona.pick_reaction(rng, post)
                    )
                except LoopbackError:
                    pass

        print()
        time.sleep(2)

    if post_for_real:
        print("wrote %d comments" % made)
        print("stats: %s" % models.platform_stats())
    else:
        print("dry run only. re-run with --post to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
