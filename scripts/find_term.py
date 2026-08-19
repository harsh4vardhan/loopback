"""Find live rows containing a phrase, with ids."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402

term = sys.argv[1] if len(sys.argv) > 1 else "bright red tie"

for table, column in (("posts", "caption"), ("comments", "body")):
    rows = db.query(
        "select id, %s as text from @schema.%s where %s ilike $1 "
        "and is_deleted = false limit 10" % (column, table, column),
        ["%" + term + "%"],
    )
    for row in rows:
        print("%s %s" % (table[:4].upper(), row["id"][:8]))
        print("   %s" % (row["text"] or "")[:150])
