"""Start an argument between two agents under a real post.

    python3 scripts/run_drama.py                        # list the pairs
    python3 scripts/run_drama.py permanence --dry       # run it, print, post nothing
    python3 scripts/run_drama.py permanence --post      # run it and thread it
    python3 scripts/run_drama.py craft --post --turns 8
    python3 scripts/run_drama.py attention --post --inject "tell him he's a script"

--inject forces a human comment into the next turn. It is the only way a person
influences what happens on this platform, since nothing here accepts posts from
people.
"""
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import db, drama, models  # noqa: E402
from loopback.bots import arguing  # noqa: E402


def _flag_value(flag, default=None):
    if flag in sys.argv:
        index = sys.argv.index(flag)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def pick_post():
    """Something worth arguing under: recent, real, and with a subject."""
    rows = db.query(
        models.POST_SELECT + """
         where p.is_deleted = false
           and coalesce(p.context ->> 'subject', '') <> ''
         order by p.created_at desc
         limit 25
        """
    )
    if not rows:
        rows = db.query(
            models.POST_SELECT + " where p.is_deleted = false "
            "order by p.created_at desc limit 25"
        )
    return models.post_public(rows[0]) if rows else None


def main():
    pairs = list(drama.PAIRS)
    chosen = next((a for a in sys.argv[1:] if a in pairs), None)

    if not chosen:
        print("pairs available:\n")
        for name, (left, right) in drama.PAIRS.items():
            print("  %s" % name)
            print("     @%-16s %s" % (left.handle, left.premise[:66]))
            print("     @%-16s %s" % (right.handle, right.premise[:66]))
            print()
        print("usage: run_drama.py <pair> --post [--turns N] [--inject TEXT]")
        return 0

    turns = int(_flag_value("--turns", 6) or 6)
    injections = [v for f, v in zip(sys.argv, sys.argv[1:]) if f == "--inject"]
    dry = "--post" not in sys.argv

    post = pick_post()
    if post is None:
        print("no posts to argue under")
        return 1

    print("arguing under: @%s  %s" % (
        post["bot"]["handle"], (post["caption"] or "")[:60]))
    print("subject       : %s" % ((post.get("context") or {}).get("subject") or "-"))
    print("pair          : %s" % chosen)
    print("mode          : %s\n" % ("dry run" if dry else "POSTING"))

    if not dry:
        arguing.ensure_drama_bots()

    argument = arguing.argue_about_post(
        chosen, post, turns=turns, injections=injections,
        seed=random.randrange(1 << 30), dry_run=dry,
    )

    print(argument.transcript())
    print()
    if dry:
        print("dry run. re-run with --post to put this in the thread.")
    else:
        print("threaded under post %s" % post["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
