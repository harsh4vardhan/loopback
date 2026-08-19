"""Wipe the platform and let it rebuild itself from an empty database.

Drops the whole schema, then recreates it. The house bots are seeded on the
next boot and the scheduler starts from nothing, so the feed that follows is
entirely produced by the current code rather than being a mix of old and new.

Requires --yes. Prints what it is about to destroy first.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import config, db, schema  # noqa: E402


def main():
    print("target: schema %r on %s" % (
        config.DB_SCHEMA,
        (config.DATABASE_URL.split("@")[-1].split("/")[0] or "?"),
    ))

    try:
        rows = db.query(
            """
            select table_name,
                   (xpath('/row/c/text()',
                     query_to_xml(format('select count(*) as c from %I.%I',
                       table_schema, table_name), false, true, '')))[1]::text::int
                   as n
              from information_schema.tables
             where table_schema = $1
             order by table_name
            """,
            [config.DB_SCHEMA],
        )
    except db.DatabaseError as exc:
        print("could not inspect: %s" % exc)
        return 1

    if not rows:
        print("nothing there already")
    else:
        total = 0
        for row in rows:
            print("  %-14s %6d rows" % (row["table_name"], row["n"]))
            total += int(row["n"])
        print("  %-14s %6d rows total" % ("", total))

    if "--yes" not in sys.argv:
        print("\nre-run with --yes to destroy this")
        return 0

    schema.drop_all()
    schema.migrate()
    print("\nschema %r dropped and recreated, empty." % config.DB_SCHEMA)
    print("The house bots are seeded on the next server boot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
