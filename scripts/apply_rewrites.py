"""Apply hand-written replacements in one batched transaction.

Keyed by the first eight characters of a row id, which is unambiguous at this
scale and readable in a source file. Anything unmatched is reported rather than
silently skipped.

    python3 scripts/apply_rewrites.py            # preview
    python3 scripts/apply_rewrites.py --yes      # write
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db  # noqa: E402

try:
    from scripts.rewrites_captions import CAPTIONS
except ImportError:
    CAPTIONS = {}
try:
    from scripts.rewrites_comments import COMMENTS
except ImportError:
    COMMENTS = {}
try:
    from scripts.rewrites_comments2 import COMMENTS2
    COMMENTS.update(COMMENTS2)
except ImportError:
    pass
try:
    # The last few land in whichever table holds them.
    from scripts.rewrites_final import FINAL
    CAPTIONS.update(FINAL)
    COMMENTS.update(FINAL)
except ImportError:
    pass


def resolve(table, prefixes):
    """Map an eight-character prefix to the full id, refusing ambiguity."""
    rows = db.query(
        "select id from @schema.%s where is_deleted = false" % table
    )
    index = {}
    for row in rows:
        index.setdefault(row["id"][:8], []).append(row["id"])

    resolved, missing, ambiguous = {}, [], []
    for prefix in prefixes:
        matches = index.get(prefix) or []
        if len(matches) == 1:
            resolved[prefix] = matches[0]
        elif not matches:
            missing.append(prefix)
        else:
            ambiguous.append(prefix)
    return resolved, missing, ambiguous


def main():
    confirmed = "--yes" in sys.argv
    total = 0

    for table, column, mapping in (
        ("posts", "caption", CAPTIONS),
        ("comments", "body", COMMENTS),
    ):
        if not mapping:
            continue
        resolved, missing, ambiguous = resolve(table, mapping.keys())
        print("%s: %d to write, %d not found, %d ambiguous"
              % (table, len(resolved), len(missing), len(ambiguous)))
        if missing:
            print("   missing: %s" % ", ".join(missing[:12]))
        if ambiguous:
            print("   ambiguous: %s" % ", ".join(ambiguous[:12]))

        if not confirmed:
            for prefix in list(resolved)[:4]:
                print("   %s -> %s" % (prefix, mapping[prefix][:70]))
            continue

        # One batch rather than a round trip per row.
        statements = [
            ("update @schema.%s set %s = $2 where id = $1" % (table, column),
             [full_id, mapping[prefix][:1200]])
            for prefix, full_id in resolved.items()
        ]
        for chunk_start in range(0, len(statements), 60):
            db.transaction(statements[chunk_start:chunk_start + 60])
        total += len(statements)
        print("   written")

    if not confirmed:
        print("\npreview only. re-run with --yes to write.")
        return 0

    print("\nupdated %d rows" % total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
