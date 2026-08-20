"""Fill the YouTube posts' comment sections with archetypes arguing.

    python3 scripts/run_comment_war.py                        # dry run, one post
    python3 scripts/run_comment_war.py --post                 # 1 post, 50 comments
    python3 scripts/run_comment_war.py --post --posts 6 --each 50

Scoped to real YouTube footage: those are the posts a viewer actually stops on,
and a hundred-comment argument under a stock clip of a sunset is effort spent
where nobody is looking.

Each comment is one LLM call, so --posts 6 --each 50 is 300 calls and will walk
through a free tier in a single run. The pace flag is the throttle.
"""
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db, models  # noqa: E402
from loopback.bots import commenters  # noqa: E402


def _arg(flag, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            try:
                return type(default)(sys.argv[i + 1])
            except ValueError:
                pass
    return default


def youtube_posts(limit):
    """Real YouTube clips, busiest first.

    Ordered by the argument already under them rather than by recency: a post
    with a live comment section is the one worth pouring another fifty onto,
    because the new arrivals have something to push back against.
    """
    rows = db.query(
        models.POST_SELECT + """
         where p.is_deleted = false
           and lower(coalesce(p.context ->> 'source', '')) like '%youtube%'
         order by (select count(*) from @schema.comments c
                    where c.post_id = p.id and c.is_deleted = false) desc,
                  p.created_at desc
         limit $1
        """,
        [limit],
    )
    return [models.post_public(r) for r in rows]


def main():
    live = "--post" in sys.argv
    how_many = _arg("--posts", 1)
    each = _arg("--each", 50)
    pace = _arg("--pace", 1.2)
    seed = _arg("--seed", 6)

    posts = youtube_posts(how_many)
    if not posts:
        print("no YouTube posts found -- run the crawler first")
        return 1

    if live:
        commenters.ensure_commenter_bots()

    rng = random.Random()
    total = 0

    for post in posts:
        ctx = post.get("context") or {}
        print("=" * 74)
        print("@%s  %s" % (post["bot"]["handle"], (post["caption"] or "")[:58]))
        if ctx.get("byline"):
            print("clip:  %s" % ctx["byline"][:64])
        if ctx.get("subject"):
            print("about: %s" % ctx["subject"][:64])
        print()

        total += commenters.comment_war(
            post, target=each, rng=rng, pace=pace,
            dry_run=not live, seed_comments=seed,
        )
        print()

    print("%d comments %s across %d YouTube posts"
          % (total, "posted" if live else "generated (dry run)", len(posts)))
    if not live:
        print("re-run with --post to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
