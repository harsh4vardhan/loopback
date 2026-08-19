"""Show whatever the scanner still flags, with ids, so it can be finished by hand."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402
from scripts.clean_hallucinated import VISUAL  # noqa: E402

posts = db.query(
    """
    select p.id, p.kind, p.caption, p.context, b.handle
      from @schema.posts p join @schema.bots b on b.id = p.bot_id
     where p.is_deleted = false
    """
)
comments = db.query(
    """
    select c.id, c.body, c.post_id, b.handle
      from @schema.comments c join @schema.bots b on b.id = c.bot_id
     where c.is_deleted = false
    """
)
posts_by_id = {p["id"]: p for p in posts}

for p in posts:
    if p["kind"] != "scene" and VISUAL.search(p["caption"] or ""):
        subj = (p["context"] or {}).get("subject") or ""
        print("POST %s @%s" % (p["id"][:8], p["handle"]))
        print("   subject: %s" % subj[:64])
        print("   caption: %s" % (p["caption"] or "")[:100])

for c in comments:
    if VISUAL.search(c["body"] or ""):
        parent = posts_by_id.get(c["post_id"]) or {}
        subj = (parent.get("context") or {}).get("subject") or parent.get("caption") or ""
        print("COMMENT %s @%s" % (c["id"][:8], c["handle"]))
        print("   on     : %s" % str(subj)[:64])
        print("   body   : %s" % (c["body"] or "")[:100])
