"""Export invented lines together with everything genuinely known about them.

The point is to have the real material beside each bad line -- the subject, the
video's actual title, the uploader, their description, and for a reply the
parent comment -- so a replacement can be written from fact rather than
regenerated blind.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402
from scripts.clean_hallucinated import VISUAL  # noqa: E402

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "var/rewrite.json")

posts = db.query(
    """
    select p.id, p.kind, p.caption, p.media, p.context, b.handle
      from @schema.posts p join @schema.bots b on b.id = p.bot_id
     where p.is_deleted = false
     order by p.created_at desc
    """
)
comments = db.query(
    """
    select c.id, c.post_id, c.parent_id, c.body, b.handle
      from @schema.comments c join @schema.bots b on b.id = c.bot_id
     where c.is_deleted = false
     order by c.created_at asc
    """
)

posts_by_id = {p["id"]: p for p in posts}
comments_by_id = {c["id"]: c for c in comments}


def facts(post):
    ctx = post.get("context") or {}
    media = post.get("media") or {}
    return {
        "subject": ctx.get("subject") or "",
        "video_title": media.get("title") or "",
        "uploader": ctx.get("byline") or "",
        "description": (ctx.get("description") or ctx.get("blurb") or "")[:300],
        "tags": ctx.get("tags") or [],
        "source": ctx.get("source") or media.get("host") or "",
        "kind": post.get("kind"),
    }


bad_posts = [
    {
        "id": p["id"], "handle": p["handle"], "old": p["caption"],
        "facts": facts(p),
    }
    for p in posts
    if p["kind"] != "scene" and VISUAL.search(p["caption"] or "")
]

bad_comments = []
for c in comments:
    if not VISUAL.search(c["body"] or ""):
        continue
    post = posts_by_id.get(c["post_id"])
    if not post:
        continue
    parent = comments_by_id.get(c["parent_id"]) if c["parent_id"] else None
    bad_comments.append({
        "id": c["id"], "handle": c["handle"], "old": c["body"],
        "post_caption": post["caption"],
        "facts": facts(post),
        "replying_to": (
            {"handle": parent["handle"], "body": parent["body"]} if parent else None
        ),
    })

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(
    {"posts": bad_posts, "comments": bad_comments}, indent=1, default=str
), encoding="utf-8")

print("wrote %s" % OUT)
print("  captions: %d" % len(bad_posts))
print("  comments: %d" % len(bad_comments))
