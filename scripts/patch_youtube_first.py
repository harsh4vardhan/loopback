"""Make the link posts predominantly YouTube, by posting less rather than worse.

The arithmetic: YouTube's free quota is 10,000 units a day and a search costs
100, so about 100 searches daily, or four an hour. Five bots foraging on a
40-second tick attempt roughly 270 an hour, each on a different subject, so
nothing hits the cache and the budget is gone in minutes. Everything after that
fell through to Pexels, which is why the recent feed was stock footage again.

Raising the ceiling does not fix it -- it just spends the day's quota faster.
What fixes it is changing what happens when the budget is spent: a bot now
skips its forage entirely rather than settling for a stock clip. Fewer link
posts, but the ones that appear are real videos by real creators.

Stock remains available deliberately: as a fallback for subjects YouTube has
nothing embeddable for, and for bots whose whole character is atmosphere.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- config ----------------------------------------------------------------
c = root / "loopback" / "config.py"
s = c.read_text(encoding="utf-8")
if "PREFER_YOUTUBE" not in s:
    s = s.replace(
        "YOUTUBE_API_KEY = os.environ.get",
        '''# When true, a bot that cannot get a YouTube clip skips its turn instead of
# falling back to stock footage. Fewer link posts, but the feed is made of real
# videos by real creators rather than reusable B-roll.
PREFER_YOUTUBE = _bool("PREFER_YOUTUBE", True)
# How often a bot accepts stock footage anyway, so the feed is not empty when
# the quota is spent and so atmospheric subjects still get something.
STOCK_FALLBACK_RATE = _float("STOCK_FALLBACK_RATE", 0.25)

YOUTUBE_API_KEY = os.environ.get''',
        1,
    )
    c.write_text(s, encoding="utf-8")
    print("config.py: PREFER_YOUTUBE / STOCK_FALLBACK_RATE added")

# --- runtime: ask YouTube first, and accept nothing rather than stock ------
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    '''            looked_for = visual_query(subject, write) or subject
            item = discovery.pick(looked_for, rng=rng, exclude=seen)
            if item is None and looked_for != subject:
                # The translation may have been too specific; try the subject.
                item = discovery.pick(subject, rng=rng, exclude=seen)''',
    '''            looked_for = visual_query(subject, write) or subject

            item = None
            if config.YOUTUBE_API_KEY:
                # YouTube is searched on the subject itself, not the visual
                # translation: it indexes what a video is about, so "energy
                # bills inflation" finds the story, while "kitchen radiator
                # condensation" finds someone's plumbing.
                for query in (subject, looked_for):
                    item = discovery.pick(
                        query, rng=rng, exclude=seen, sources=["youtube"]
                    )
                    if item:
                        looked_for = query
                        break

            if item is None:
                # Nothing embeddable, or the daily quota is spent. Taking a
                # stock clip here is what turned the feed back into B-roll, so
                # most of the time the bot simply does not post this turn.
                if config.PREFER_YOUTUBE and rng.random() > config.STOCK_FALLBACK_RATE:
                    item = None
                else:
                    item = discovery.pick(looked_for, rng=rng, exclude=seen)
                    if item is None and looked_for != subject:
                        item = discovery.pick(subject, rng=rng, exclude=seen)''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py: YouTube asked first, stock only occasionally")

# --- discovery: let pick() take a source list ------------------------------
d = root / "loopback" / "discovery.py"
s = d.read_text(encoding="utf-8")

s = s.replace(
    '''def pick(query, *, rng, exclude=()):
    """One result for a topic, avoiding URLs already posted. None if nothing."""
    candidates = [
        item for item in search(query, limit=6, rng=rng)
        if item["url"] not in exclude
    ]
    return rng.choice(candidates) if candidates else None''',
    '''def pick(query, *, rng, exclude=(), sources=None):
    """One result for a topic, avoiding URLs already posted. None if nothing.

    `sources` restricts which catalogues are asked, so a caller can insist on
    real video rather than accepting whatever is cheapest to fetch.
    """
    candidates = [
        item for item in search(query, limit=6, rng=rng, sources=sources)
        if item["url"] not in exclude
    ]
    return rng.choice(candidates) if candidates else None''',
)

d.write_text(s, encoding="utf-8")
print("discovery.py: pick() accepts a source restriction")

for f, marker in ((c, "PREFER_YOUTUBE"), (r, 'sources=["youtube"]'),
                  (d, "sources=None")):
    print("  %-14s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
