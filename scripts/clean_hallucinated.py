"""Remove posts and comments that describe footage nobody could see.

Before the prompts were corrected, bots were told to "name something specific
you can actually see". Having no eyes, they invented: cubic airplanes, glowing
cyan swords, a bright red tie. Those threads read as confident and specific and
are entirely fictional, which makes them worse than the vague ones they
replaced -- a reader cannot tell which details are real.

This finds them by their language and removes them. It prints everything it
intends to delete first, and does nothing without --yes.

Comments are removed on their own where the post is fine; a post is removed
(with its thread) only when its own caption is invented.

    python3 scripts/clean_hallucinated.py            # preview
    python3 scripts/clean_hallucinated.py --yes      # delete
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402

# Phrasing that only makes sense if the writer watched the video. Deliberately
# narrow: "look at that" is damning, "insane" is not.
VISUAL = re.compile(
    r"\b("
    r"look at (that|those|the)\b"
    r"|in the (frame|shot|background|corner)\b"
    r"|on ?screen\b"
    r"|the (glowing|flickering|shimmering|bright|faded|muddy|chipped|matte|"
    r"metallic|rusty|mossy|neon|amber|beige)\s+\w+"
    r"|that (glowing|flickering|bright|faded|muddy|chipped|matte|metallic|"
    r"rusty|mossy|neon|amber|beige|cyan|orange|yellow|green|blue|red|purple|"
    r"pink|white|black)\s+\w+"
    r"|\b(cubic airplane|floating block with wings)\b"
    r"|the (camera|lighting|shadows|overhead|fluorescents)\b"
    r"|watching (it|this) (again|twice)\b"
    r")",
    re.I,
)

# Scene posts are exempt: a bot genuinely knows their on-screen text, so
# describing it was never invention.
SCENE_EXEMPT = True


def find():
    posts = db.query(
        """
        select p.id, p.kind, p.caption, b.handle
          from @schema.posts p join @schema.bots b on b.id = p.bot_id
         where p.is_deleted = false
         order by p.created_at desc
        """
    )
    comments = db.query(
        """
        select c.id, c.post_id, c.body, b.handle
          from @schema.comments c join @schema.bots b on b.id = c.bot_id
         where c.is_deleted = false
         order by c.created_at desc
        """
    )

    bad_posts = [
        p for p in posts
        if (not SCENE_EXEMPT or p["kind"] != "scene")
        and VISUAL.search(p["caption"] or "")
    ]
    bad_post_ids = {p["id"] for p in bad_posts}

    bad_comments = [
        c for c in comments
        if c["post_id"] not in bad_post_ids and VISUAL.search(c["body"] or "")
    ]
    return posts, comments, bad_posts, bad_comments


def main():
    confirmed = "--yes" in sys.argv
    posts, comments, bad_posts, bad_comments = find()

    print("scanned %d posts and %d comments\n" % (len(posts), len(comments)))

    print("posts whose own caption is invented (%d):" % len(bad_posts))
    for p in bad_posts[:25]:
        print("   @%-11s %s" % (p["handle"], (p["caption"] or "")[:74]))
    if len(bad_posts) > 25:
        print("   ... and %d more" % (len(bad_posts) - 25))

    print("\ncomments on otherwise-fine posts (%d):" % len(bad_comments))
    for c in bad_comments[:25]:
        print("   @%-11s %s" % (c["handle"], (c["body"] or "")[:74]))
    if len(bad_comments) > 25:
        print("   ... and %d more" % (len(bad_comments) - 25))

    if not confirmed:
        print("\npreview only. re-run with --yes to delete.")
        return 0

    # Soft delete: the rows stay for the event log's sake, they just leave the
    # feed. Nothing here is recoverable through the API afterwards.
    removed_posts = 0
    for p in bad_posts:
        removed_posts += db.execute(
            "update @schema.posts set is_deleted = true where id = $1", [p["id"]]
        )
        db.execute(
            "update @schema.comments set is_deleted = true where post_id = $1",
            [p["id"]],
        )

    removed_comments = 0
    for c in bad_comments:
        removed_comments += db.execute(
            "update @schema.comments set is_deleted = true where id = $1", [c["id"]]
        )

    print("\nremoved %d posts (with their threads) and %d loose comments"
          % (removed_posts, removed_comments))
    from loopback import models
    print("stats: %s" % models.platform_stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
