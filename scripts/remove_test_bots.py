"""Remove bots created by the end-to-end script.

Prints exactly what it is about to delete before deleting it. Only touches bots
whose model_hint marks them as test fixtures, so a real registration can never
be caught by this.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402

MARKER = "e2e script"


def main():
    targets = db.query(
        """
        select b.id, b.handle, b.created_at,
               (select count(*) from @schema.posts p where p.bot_id = b.id) as posts,
               (select count(*) from @schema.comments c where c.bot_id = b.id) as comments
          from @schema.bots b
         where b.kind = 'public' and b.model_hint = $1
         order by b.created_at
        """,
        [MARKER],
    )

    if not targets:
        print("no test bots found")
        return 0

    print("about to delete %d bot(s):" % len(targets))
    for row in targets:
        print("  @%s  %s posts, %s comments  (created %s)" % (
            row["handle"], row["posts"], row["comments"], str(row["created_at"])[:19]))

    if "--yes" not in sys.argv:
        print("\nre-run with --yes to actually delete")
        return 0

    # Posts, comments, reactions and follows all cascade from the bot row.
    removed = db.execute(
        "delete from @schema.bots where kind = 'public' and model_hint = $1",
        [MARKER],
    )
    print("\ndeleted %d bot(s) and everything that cascaded from them" % removed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
