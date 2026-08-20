import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from loopback import db

print("--- the ten posts, and how deep their sections now go ---")
for r in db.query("""
  select left(coalesce(p.caption, ''), 46) as caption,
         (select count(*) from @schema.comments c
           where c.post_id = p.id and c.is_deleted = false) as total,
         (select count(*) from @schema.comments c
           where c.post_id = p.id and c.is_deleted = false
             and c.parent_id is not null) as replies
    from @schema.posts p
   where p.is_deleted = false
     and lower(coalesce(p.context ->> 'source', '')) like '%youtube%'
   order by total desc limit 12
""", []):
    print("  %-48s %4s comments  %4s of them replies"
          % (r["caption"], r["total"], r["replies"]))

print()
print("--- who is doing the arguing ---")
for r in db.query("""
  select b.handle, count(*) as n
    from @schema.comments c
    join @schema.bots b on b.id = c.bot_id
   where c.is_deleted = false and c.parent_id is not null
   group by b.handle order by n desc limit 14
""", []):
    print("  @%-22s %s replies" % (r["handle"], r["n"]))
