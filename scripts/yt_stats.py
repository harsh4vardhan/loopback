import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from loopback import db

rows = db.query("""
  select count(*) as posts,
         coalesce(sum((select count(*) from @schema.comments c
                        where c.post_id = p.id and c.is_deleted = false)), 0) as comments
    from @schema.posts p
   where p.is_deleted = false
     and lower(coalesce(p.context ->> 'source', '')) like '%youtube%'
""", [])
print("youtube posts: %s   comments on them: %s" % (rows[0]["posts"], rows[0]["comments"]))
