"""Give bots a little grounding before they speak, and make gaming reliable.

Two changes:

  * trends.context() looks a subject up on Wikipedia and returns a short
    factual summary. It is attached to a post before a persona comments, so a
    bot writes about the thing rather than about the words in the caption.
  * Gaming was matching almost nothing, because the pattern was generic and
    Wikipedia's most-read list names specific titles. The pattern now covers
    actual franchises, and each category has a seed list so a thin day
    degrades to a related subject instead of an unrelated one.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
p = root / "loopback" / "trends.py"
s = p.read_text(encoding="utf-8")

# --- a gaming pattern that matches how these subjects are actually titled ---
s = s.replace(
    '''_GAMING = re.compile(
    r"\\b(game|gaming|nintendo|playstation|xbox|steam|valve|minecraft|roblox|"
    r"esport|speedrun|rpg|fps|indie game|console)\\b", re.I
)''',
    '''# Wikipedia's most-read list names specific titles, not the word "gaming", so
# matching the category means matching franchises.
_GAMING = re.compile(
    r"\\b(video ?game|gaming|nintendo|playstation|ps5|xbox|steam ?deck|valve|"
    r"minecraft|roblox|fortnite|grand theft auto|gta ?\\d?|elden ring|zelda|"
    r"mario|pok[eé]mon|call of duty|counter.?strike|valorant|league of legends|"
    r"dota|overwatch|apex legends|battlefield|assassin.s creed|cyberpunk 2077|"
    r"starfield|baldur.s gate|silksong|hollow knight|the sims|halo|"
    r"final fantasy|resident evil|rockstar games|ubisoft|bethesda|blizzard|"
    r"esports?|speedrun|twitch|nintendo switch|game awards)\\b", re.I
)''',
)

# --- seeds, so a category is never empty and never off-topic ---------------
s = s.replace(
    'CATEGORIES = ("news", "gaming", "technology", "culture", "anything")',
    '''CATEGORIES = ("news", "gaming", "technology", "culture", "anything")

# When nothing in a category is trending, a bot should still get a subject that
# belongs to that category rather than an unrelated one. These are evergreen
# enough to survive as filler and are only used when the live pool comes up dry.
SEED_TOPICS = {
    "gaming": [
        "Grand Theft Auto VI", "Nintendo Switch", "Elden Ring", "Minecraft",
        "speedrunning", "Counter-Strike", "The Legend of Zelda", "esports",
    ],
    "technology": [
        "large language models", "open source software", "semiconductors",
        "data centres", "undersea cables",
    ],
    "news": ["weather systems", "elections", "world records", "space launches"],
    "culture": ["film scores", "brutalist architecture", "night photography"],
    "anything": ["tides", "clocks", "storms", "aurora"],
}''',
)

s = s.replace(
    '''    # A narrow category is often empty on a given day -- nothing gaming-related
    # trends every hour. Fall back to the general pool rather than leaving a bot
    # with nothing to talk about.
    if not pool:
        pool = wiki + news

    return pool[:limit]''',
    '''    # A narrow category is often empty on a given day -- nothing gaming-related
    # trends every hour. Fall back within the category first, so a gaming bot
    # gets a gaming subject rather than whatever happened to be popular.
    if not pool:
        pool = [
            {"subject": seed, "source": "seed (%s)" % category,
             "url": None, "blurb": "", "rank": index + 1}
            for index, seed in enumerate(
                SEED_TOPICS.get(category) or SEED_TOPICS["anything"]
            )
        ]

    return pool[:limit]''',
)

# --- grounding -------------------------------------------------------------
s = s.replace(
    'def status():',
    '''def context(subject, *, max_chars=420):
    """A short factual summary of a subject, or None.

    Used to ground a bot before it comments. Wikipedia's REST summary endpoint
    is public, keyless, and returns a lead paragraph, which is exactly the
    amount of context a one-line remark needs.
    """
    subject = " ".join(str(subject or "").split())[:120]
    if not subject:
        return None

    def fetch():
        url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
               + urllib.parse.quote(subject.replace(" ", "_"), safe=""))
        data = _get_json(url)
        if data.get("type", "").endswith("not_found"):
            return None
        extract = (data.get("extract") or "").strip()
        if not extract:
            return None
        return {
            "subject": subject,
            "summary": extract[:max_chars],
            "url": ((data.get("content_urls") or {}).get("desktop") or {}).get("page"),
        }

    return _cached("summary:%s" % subject.lower(), fetch) or None


def status():''',
)

p.write_text(s, encoding="utf-8")
print("trends.py patched")
for marker in ("SEED_TOPICS", "grand theft auto", "def context("):
    print("  %-20s %s" % (marker, "present" if marker in s else "MISSING"))
