"""Prove the Neon HTTP transport works before anything is built on top of it."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import config, db, schema  # noqa: E402


def main():
    print("config:", config.summary())

    ok, detail = db.healthcheck()
    print("healthcheck:", "OK" if ok else "FAILED", detail)
    if not ok:
        return 1

    print("qualify() sample:", db.qualify("select * from @schema.posts limit 1"))

    print("migrating...")
    count = schema.migrate()
    print("applied %d statements" % count)

    tables = db.query(
        """
        select table_name
          from information_schema.tables
         where table_schema = $1
         order by table_name
        """,
        [config.DB_SCHEMA],
    )
    print("tables in %r: %s" % (
        config.DB_SCHEMA, ", ".join(t["table_name"] for t in tables) or "(none)"
    ))

    print("stats:", __import__("loopback.models", fromlist=["x"]).platform_stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
