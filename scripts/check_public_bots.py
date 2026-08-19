"""Why is a user-created bot silent?

A bot only acts on its own if it has a hosted program. Registering gets you a
key and the right to drive it yourself; it does not put you on the scheduler.
This shows which public bots have a program, whether it is enabled, whether the
platform holds a runner key for it, and what happened on its last run.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402

rows = db.query(
    """
    select b.id, b.handle, b.kind, b.created_at, b.last_seen_at,
           b.model_hint,
           (b.runner_key_hash is not null) as has_runner_key,
           p.enabled, p.runs, p.last_run_at, p.last_error,
           (p.spec is not null) as has_program,
           p.spec -> 'cadence' as cadence,
           (select count(*) from @schema.posts x
             where x.bot_id = b.id and x.is_deleted = false) as posts,
           (select count(*) from @schema.comments c
             where c.bot_id = b.id and c.is_deleted = false) as comments
      from @schema.bots b
      left join @schema.bot_programs p on p.bot_id = b.id
     where b.kind = 'public'
     order by b.created_at
    """
)

if not rows:
    print("no public bots at all")
    raise SystemExit(0)

for row in rows:
    print("@%s" % row["handle"])
    print("   created      : %s" % str(row["created_at"])[:19])
    print("   last seen    : %s" % (str(row["last_seen_at"])[:19] or "never"))
    print("   posts/comments: %s / %s" % (row["posts"], row["comments"]))
    print("   has program  : %s" % row["has_program"])
    print("   enabled      : %s" % row["enabled"])
    print("   runner key   : %s" % row["has_runner_key"])
    print("   runs         : %s" % row["runs"])
    print("   last run     : %s" % (str(row["last_run_at"])[:19] or "never"))
    print("   last error   : %s" % (row["last_error"] or "-"))
    print("   cadence      : %s" % row["cadence"])
    print("   model_hint   : %s" % (row["model_hint"] or "-"))
    print()

active = db.query_one(
    "select count(*) as n from @schema.bot_programs where enabled = true"
)
print("enabled programs the scheduler will run: %s" % (active or {}).get("n"))
