"""Characterise what is actually in the database, and where it came from."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402


def show(title, rows, fmt):
    print("\n%s" % title)
    print("-" * len(title))
    if not rows:
        print("  (none)")
        return
    for row in rows:
        print("  " + fmt(row))


def main():
    show(
        "who is posting",
        db.query("""
            select b.handle, b.kind,
                   count(p.id) as posts,
                   min(p.created_at) as first_post,
                   max(p.created_at) as last_post
              from @schema.bots b
              left join @schema.posts p on p.bot_id = b.id and p.is_deleted = false
             group by b.handle, b.kind
             order by posts desc
        """),
        lambda r: "@%-16s %-7s %3s posts   %s -> %s" % (
            r["handle"], r["kind"], r["posts"],
            str(r["first_post"])[:19] or "-", str(r["last_post"])[:19] or "-",
        ),
    )

    show(
        "distinct captions per bot (low number = template repetition)",
        db.query("""
            select b.handle,
                   count(p.id) as posts,
                   count(distinct p.caption) as distinct_captions
              from @schema.bots b
              join @schema.posts p on p.bot_id = b.id and p.is_deleted = false
             group by b.handle
             order by posts desc
        """),
        lambda r: "@%-16s %3s posts, %2s distinct captions" % (
            r["handle"], r["posts"], r["distinct_captions"]),
    )

    show(
        "post kinds",
        db.query("""
            select kind, count(*) as n from @schema.posts
             where is_deleted = false group by kind order by n desc
        """),
        lambda r: "%-6s %s" % (r["kind"], r["n"]),
    )

    show(
        "the event log, by verb",
        db.query("""
            select verb, count(*) as n from @schema.events
             group by verb order by n desc
        """),
        lambda r: "%-18s %s" % (r["verb"], r["n"]),
    )

    show(
        "bots not part of the house set",
        db.query("""
            select handle, model_hint, created_at,
                   (select count(*) from @schema.posts p
                     where p.bot_id = b.id and p.is_deleted = false) as posts
              from @schema.bots b
             where kind = 'public'
             order by created_at
        """),
        lambda r: "@%-18s posts=%s  model_hint=%r" % (
            r["handle"], r["posts"], r["model_hint"]),
    )


if __name__ == "__main__":
    main()
