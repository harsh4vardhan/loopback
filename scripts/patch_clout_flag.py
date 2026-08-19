"""Expose clout mode on the runner and the post-threading helper."""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

r = root / "scripts" / "run_drama.py"
s = r.read_text(encoding="utf-8")

if "--clout" not in s:
    s = s.replace(
        '    print("mode          : %s\\n" % ("dry run" if dry else "POSTING"))',
        '    mode = "clout" if "--clout" in sys.argv else "ladder"\n'
        '    print("register      : %s" % mode)\n'
        '    print("mode          : %s\\n" % ("dry run" if dry else "POSTING"))',
    )
    s = s.replace(
        "        seed=random.randrange(1 << 30), dry_run=dry,\n    )",
        "        seed=random.randrange(1 << 30), dry_run=dry, mode=mode,\n    )",
    )
    s = s.replace(
        '--inject forces a human comment',
        '--clout switches register: short reactive rants instead of a staged\nargument. Both stay available because they fail differently -- the ladder can\nget donnish, clout mode can get shallow.\n\n--inject forces a human comment',
    )
    r.write_text(s, encoding="utf-8")
    print("run_drama.py: --clout added")

a = root / "loopback" / "bots" / "arguing.py"
t = a.read_text(encoding="utf-8")
if "mode=\"ladder\"" not in t:
    t = t.replace(
        "def argue_about_post(pair_name, post, *, turns=6, injections=(), seed=None,\n"
        "                     pace=2.0, dry_run=False):",
        "def argue_about_post(pair_name, post, *, turns=6, injections=(), seed=None,\n"
        "                     pace=2.0, dry_run=False, mode=\"ladder\"):",
    )
    t = t.replace(
        "    argument.run(writer(), turns=turns)",
        "    argument.run(writer(), turns=turns, mode=mode)",
    )
    a.write_text(t, encoding="utf-8")
    print("arguing.py: mode threaded through")

for f, marker in ((r, "--clout"), (a, 'mode="ladder"')):
    print("  %-16s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
