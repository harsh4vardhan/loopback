"""Stop one commenter absorbing the whole argument.

On the first post @no_hesitation was replied to twelve times and several
archetypes were never answered at all -- FRICTION lists point at it from many
sides, so uniform random picking concentrates there. Real sections do have a
dominant thread, but not to the exclusion of every other one.

Picks the least-answered candidate out of a small random sample, which keeps
the choice varied while pushing steadily toward spread.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "bots" / "commenters.py"
s = p.read_text(encoding="utf-8")

old = r'''        parent = responder_handle = None
        for _ in range(24):
            candidate = rng.choice(pool)
            who = _antagonist_for(candidate["bot_handle"], rng, available)
            if who and (candidate.get("id"), who) not in spoken:
                parent, responder_handle = candidate, who
                break'''
new = r'''        parent = responder_handle = None
        best = None
        for _ in range(24):
            candidate = rng.choice(pool)
            who = _antagonist_for(candidate["bot_handle"], rng, available)
            if not who or (candidate.get("id"), who) not in spoken:
                if not who:
                    continue
                # Among valid pairings, favour whoever has been answered least,
                # so the argument spreads instead of collapsing onto one bot.
                cost = answered[candidate["bot_handle"]] + answered[who]
                if best is None or cost < best[0]:
                    best = (cost, candidate, who)
                if cost == 0:
                    break
        if best:
            _, parent, responder_handle = best'''
assert old in s, "pairing search not found"
s = s.replace(old, new)

s = s.replace(
    r'''        spoken.add((parent.get("id"), responder_handle))''',
    r'''        spoken.add((parent.get("id"), responder_handle))
        answered[parent["bot_handle"]] += 1
        answered[responder_handle] += 1''',
)

s = s.replace(
    r'''    skipped = 0         # replies withheld for saying nothing''',
    r'''    skipped = 0         # replies withheld for saying nothing
    answered = collections.Counter()   # how much of the argument each bot owns''',
)
s = s.replace("import hashlib", "import collections\nimport hashlib")

p.write_text(s, encoding="utf-8")
print("commenters.py: argument spread across more commenters")
