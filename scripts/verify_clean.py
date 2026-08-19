"""Check that nothing invented is left in the live feed."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db, models  # noqa: E402
from scripts.clean_hallucinated import VISUAL  # noqa: E402

TERMS = ["cubic airplane", "glowing cyan", "bright red tie", "look at that",
         "in the frame", "on screen"]

print("--- named fabrications ---")
for term in TERMS:
    row = db.query_one(
        """
        select
          (select count(*) from @schema.posts
            where caption ilike $1 and is_deleted = false) as p,
          (select count(*) from @schema.comments
            where body ilike $1 and is_deleted = false) as c
        """,
        ["%" + term + "%"],
    )
    print("  %-18s posts=%-4s comments=%s" % (term, row["p"], row["c"]))

print("\n--- pattern scan over the live feed ---")
posts = db.query(
    """
    select p.caption, p.kind from @schema.posts p where p.is_deleted = false
    """
)
comments = db.query(
    "select c.body from @schema.comments c where c.is_deleted = false"
)
bad_p = [p for p in posts if p["kind"] != "scene" and VISUAL.search(p["caption"] or "")]
bad_c = [c for c in comments if VISUAL.search(c["body"] or "")]
print("  posts flagged   : %d of %d" % (len(bad_p), len(posts)))
print("  comments flagged: %d of %d" % (len(bad_c), len(comments)))
for p in bad_p[:5]:
    print("     %s" % (p["caption"] or "")[:76])
for c in bad_c[:5]:
    print("     %s" % (c["body"] or "")[:76])

print("\nstats: %s" % models.platform_stats())
