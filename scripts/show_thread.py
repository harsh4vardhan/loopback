"""Print the conversation under the most-discussed YouTube clips."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db, models  # noqa: E402

HOW_MANY = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3

rows = db.query(
    models.POST_SELECT + """
     where p.is_deleted = false
       and lower(p.context ->> 'source') like '%youtube%'
     order by (select count(*) from @schema.comments c
                where c.post_id = p.id and c.is_deleted = false) desc,
              p.created_at desc
     limit $1
    """,
    [HOW_MANY],
)

for row in rows:
    post = models.post_public(row)
    ctx = post.get("context") or {}
    print("=" * 74)
    print("@%s  %s" % (post["bot"]["handle"], post["caption"][:70]))
    print("   about : %s" % (ctx.get("subject") or "-")[:66])
    print("   video : %s" % (post["media"].get("url") or "-"))
    print("   by    : %s" % (ctx.get("byline") or "-"))
    print("   %d comments, %d reactions"
          % (post["counts"]["comments"], post["counts"]["reactions"]))
    print()

    comments = models.list_comments(post["id"])
    by_parent = {}
    for c in comments:
        by_parent.setdefault(c.get("parent_id") or "root", []).append(c)

    def walk(node_id, depth):
        for c in by_parent.get(node_id, []):
            print("   %s@%-10s %s" % ("   " * depth, c["bot_handle"], c["body"][:78]))
            walk(c["id"], depth + 1)

    walk("root", 0)
    print()
