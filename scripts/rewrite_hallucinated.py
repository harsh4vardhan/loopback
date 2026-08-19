"""Rewrite invented lines from real data, rather than deleting them.

Deleting removed the threads along with the fiction. Rewriting keeps the
conversation -- the same bots, the same posts, the same reply structure -- and
replaces only the words that described footage nobody could see.

Every rewrite is generated from material that genuinely exists: the subject the
bot went looking for, the video's real title, the uploader's own description
and tags, and, for a reply, what the parent comment actually said. The personas
now carry the "you cannot see the video" rule, so regenerating through them is
what produces honest text.

Soft-deleted rows are restored as part of this: the earlier cleanup removed
whole threads, including comments that were fine.

    python3 scripts/rewrite_hallucinated.py             # preview
    python3 scripts/rewrite_hallucinated.py --yes       # rewrite and restore
    python3 scripts/rewrite_hallucinated.py --yes --limit 40
"""
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db, llm, models  # noqa: E402
from loopback.bots import hosted, personas, runtime  # noqa: E402
from scripts.clean_hallucinated import VISUAL  # noqa: E402


def _arg(flag, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            return int(sys.argv[i + 1])
    return default


def load_personas():
    """House personas plus any hosted ones, keyed by handle."""
    by_handle = dict(personas.by_handle())
    try:
        for persona in hosted.load(models.active_programs()):
            by_handle.setdefault(persona.handle, persona)
    except Exception as exc:  # noqa: BLE001
        print("  (could not load hosted personas: %s)" % str(exc)[:80])
    return by_handle


def real_item(post):
    """Everything genuinely known about the clip attached to a post."""
    context = post.get("context") or {}
    media = post.get("media") or {}
    return {
        "title": (media.get("title") or context.get("subject") or "").strip(),
        "channel": (context.get("byline") or "").strip(),
        "description": (context.get("description") or context.get("blurb") or "").strip(),
        "tags": context.get("tags") or [],
        "source": (context.get("source") or media.get("host") or "").strip(),
    }


def _say(make, used, attempts=2):
    """Generate, retrying once if the model fell through to a template."""
    text = make()
    for _ in range(attempts - 1):
        if llm.TEMPLATES not in used or len(used) > 1:
            break
        time.sleep(5)
        used.clear()
        text = make()
    return text


def main():
    confirmed = "--yes" in sys.argv
    limit = _arg("--limit", 400)

    posts = db.query(
        """
        select p.id, p.kind, p.caption, p.media, p.context, p.is_deleted,
               b.handle
          from @schema.posts p join @schema.bots b on b.id = p.bot_id
         order by p.created_at desc
        """
    )
    comments = db.query(
        """
        select c.id, c.post_id, c.parent_id, c.body, c.is_deleted, b.handle
          from @schema.comments c join @schema.bots b on b.id = c.bot_id
         order by c.created_at asc
        """
    )

    posts_by_id = {p["id"]: p for p in posts}
    comment_by_id = {c["id"]: c for c in comments}

    # A scene's on-screen text is genuinely known, so those were never invented.
    bad_posts = [
        p for p in posts
        if p["kind"] != "scene" and VISUAL.search(p["caption"] or "")
    ][:limit]
    bad_comments = [
        c for c in comments if VISUAL.search(c["body"] or "")
    ][:limit]

    restore_posts = [p for p in posts if p["is_deleted"]]
    restore_comments = [c for c in comments if c["is_deleted"]]

    print("to rewrite : %d captions, %d comments" % (len(bad_posts), len(bad_comments)))
    print("to restore : %d posts, %d comments (soft-deleted earlier)\n"
          % (len(restore_posts), len(restore_comments)))

    if not confirmed:
        for p in bad_posts[:6]:
            print("  caption @%-11s %s" % (p["handle"], (p["caption"] or "")[:70]))
        for c in bad_comments[:6]:
            print("  comment @%-11s %s" % (c["handle"], (c["body"] or "")[:70]))
        print("\npreview only. re-run with --yes to rewrite and restore.")
        return 0

    by_handle = load_personas()
    rng = random.Random(5150)

    # Restore first, so a rewritten thread is visible again as it is fixed.
    for p in restore_posts:
        db.execute("update @schema.posts set is_deleted = false where id = $1", [p["id"]])
    for c in restore_comments:
        db.execute("update @schema.comments set is_deleted = false where id = $1", [c["id"]])
    print("restored %d posts and %d comments\n" % (len(restore_posts), len(restore_comments)))

    rewritten = 0

    print("--- captions ---")
    for p in bad_posts:
        persona = by_handle.get(p["handle"])
        if persona is None:
            continue
        post = {"kind": p["kind"], "caption": p["caption"],
                "media": p["media"] or {}, "context": p["context"] or {},
                "bot": {"handle": p["handle"]}, "counts": {"comments": 0}}
        item = real_item(post)
        subject = (p["context"] or {}).get("subject") or item["title"] or "this"

        used = set()
        write = runtime._writer(persona, used, {"text": ""})
        try:
            caption = _say(
                lambda: persona.make_forage_caption(
                    rng, item, write, subject=subject
                ),
                used,
            )
        except Exception as exc:  # noqa: BLE001
            print("  @%-11s FAILED: %s" % (p["handle"], str(exc)[:60]))
            continue

        db.execute("update @schema.posts set caption = $2 where id = $1",
                   [p["id"], caption[:500]])
        rewritten += 1
        print("  @%-11s %s" % (p["handle"], caption[:74]))
        time.sleep(1.5)

    print("\n--- comments ---")
    for c in bad_comments:
        persona = by_handle.get(c["handle"])
        parent_post = posts_by_id.get(c["post_id"])
        if persona is None or parent_post is None:
            continue

        post = {"kind": parent_post["kind"], "caption": parent_post["caption"],
                "media": parent_post["media"] or {},
                "context": parent_post["context"] or {},
                "bot": {"handle": parent_post["handle"]},
                "counts": {"comments": 1, "reactions": 1}}

        used = set()
        brief = {"text": runtime._post_background(post)}
        write = runtime._writer(persona, used, brief)

        parent = comment_by_id.get(c["parent_id"]) if c["parent_id"] else None
        try:
            if parent:
                parent_obj = {"id": parent["id"], "body": parent["body"],
                              "bot": {"handle": parent["handle"]}}
                body = _say(
                    lambda: persona.make_reply(rng, post, parent_obj, write), used
                )
            else:
                body = _say(lambda: persona.make_comment(rng, post, write), used)
        except Exception as exc:  # noqa: BLE001
            print("  @%-11s FAILED: %s" % (c["handle"], str(exc)[:60]))
            continue

        db.execute("update @schema.comments set body = $2 where id = $1",
                   [c["id"], body[:1200]])
        rewritten += 1
        print("  %s@%-11s %s" % ("  " if parent else "", c["handle"], body[:72]))
        time.sleep(1.5)

    print("\nrewrote %d lines" % rewritten)
    print("stats: %s" % models.platform_stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
