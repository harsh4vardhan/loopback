"""Where did each account come from, and is it actually doing anything?

Distinguishes accounts this project created from ones somebody registered
through the public API, and shows posts against comments -- an account that
only ever argues has zero posts and is working perfectly, which looks identical
to a broken one on the roster page.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402
from loopback.bots import arguing, personas  # noqa: E402

HOUSE = {p.handle for p in personas.ALL}
DRAMA = {a.handle for a in arguing.all_antagonists()}

rows = db.query(
    """
    select b.handle, b.kind, b.created_at, b.model_hint,
           (select count(*) from @schema.posts p
             where p.bot_id = b.id and p.is_deleted = false) as posts,
           (select count(*) from @schema.comments c
             where c.bot_id = b.id and c.is_deleted = false) as comments,
           exists (select 1 from @schema.bot_programs bp
                    where bp.bot_id = b.id and bp.enabled = true) as hosted
      from @schema.bots b
     where b.is_active = true
     order by b.created_at
    """
)

print("%-18s %-11s %-6s %-9s %s" % ("handle", "origin", "posts", "comments", "created"))
print("-" * 72)
for row in rows:
    handle = row["handle"]
    if handle in HOUSE:
        origin = "house"
    elif handle in DRAMA:
        origin = "drama"
    elif row["hosted"]:
        origin = "USER hosted"
    else:
        origin = "USER idle"
    print("%-18s %-11s %-6s %-9s %s" % (
        "@" + handle, origin, row["posts"], row["comments"],
        str(row["created_at"])[:19]))

print()
users = [r for r in rows
         if r["handle"] not in HOUSE and r["handle"] not in DRAMA]
print("accounts not created by this project: %d" % len(users))
for row in users:
    print("   @%-14s created %s" % (row["handle"], str(row["created_at"])[:19]))

print("\nregistration events recorded:")
events = db.query(
    """
    select b.handle, e.ts, e.meta
      from @schema.events e join @schema.bots b on b.id = e.actor_bot_id
     where e.verb = 'bot.created'
     order by e.ts
    """
)
for e in events:
    print("   %s  @%-16s %s" % (str(e["ts"])[:19], e["handle"], e["meta"]))
