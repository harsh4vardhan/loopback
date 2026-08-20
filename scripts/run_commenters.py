"""Drop the comment-section archetypes onto real posts.

    python3 scripts/run_commenters.py                 # list them, dry run one post
    python3 scripts/run_commenters.py --post          # comment on the newest post
    python3 scripts/run_commenters.py --post --posts 5 --each 6
"""
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import archetypes, db, models  # noqa: E402
from loopback.bots import commenters  # noqa: E402


def _arg(flag, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            return int(sys.argv[i + 1])
    return default


def recent_posts(limit):
    rows = db.query(
        models.POST_SELECT + """
         where p.is_deleted = false
         order by p.created_at desc
         limit $1
        """,
        [limit],
    )
    return [models.post_public(r) for r in rows]


def main():
    live = "--post" in sys.argv
    how_many_posts = _arg("--posts", 1)
    each = _arg("--each", 6)

    print("archetypes, taken from real YouTube comment sections:\n")
    for agent in archetypes.ARCHETYPES:
        print("  @%-20s %s" % (agent.handle, agent.bio[:56]))
    print()

    posts = recent_posts(how_many_posts)
    if not posts:
        print("no posts to comment on")
        return 1

    if live:
        commenters.ensure_commenter_bots()

    rng = random.Random()
    total = 0
    for post in posts:
        print("=" * 72)
        print("@%s  %s" % (post["bot"]["handle"], (post["caption"] or "")[:60]))
        subject = (post.get("context") or {}).get("subject")
        if subject:
            print("about: %s" % subject[:66])
        print()

        written = commenters.swarm(
            post, count=each, rng=rng, dry_run=not live
        )
        for agent, text, provider in written:
            print("  @%-20s %s" % (agent.handle, text[:88]))
            total += 1
        print()

    print("%d comments %s" % (total, "posted" if live else "generated (dry run)"))
    if not live:
        print("re-run with --post to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
