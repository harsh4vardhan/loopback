"""What the world is currently paying attention to.

Bots that only ever post about tides and stairwells are atmospheric but sealed
off. This pulls a list of live subjects so the feed can be about something,
from two sources with public APIs and no keys:

  * Wikipedia's most-read articles for yesterday -- an unusually honest signal
    of mass attention, and it covers news, politics, sport and entertainment
    without anyone curating it.
  * Hacker News top stories -- technology, and by extension a lot of gaming and
    internet-culture subjects.

A note on what these are used for. Trending subjects are handed to personas as
*subject matter*, and the prompt built around them (see TOPIC_GUARDRAIL) asks
for the texture of a thing rather than a position on it. These bots are
aesthetic characters, not commentators; the platform should not become a place
where a scheduler emits political claims nobody checked.
"""
import json
import logging
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("loopback.trends")

USER_AGENT = (
    "Loopback/0.1 (a research feed of machine-authored short video; "
    "contact via the project repository)"
)

TIMEOUT = 15
CACHE_TTL = 3600  # these lists move on the order of hours, not seconds

_cache = {}
_lock = threading.Lock()

# Handed to a persona alongside a trending subject. Without it, a bot asked to
# post about an election writes like a pundit, which is not what this is.
TOPIC_GUARDRAIL = (
    "Treat this only as a subject to make something atmospheric about. Do not "
    "state facts about current events, do not take a political position, and "
    "do not report news. Write in your own voice about the feeling or texture "
    "of the subject."
)

# Categories a caller can ask for, mapped to how each source is filtered.
CATEGORIES = ("news", "gaming", "technology", "culture", "anything")

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
}

# Wikipedia's most-read list names specific titles, not the word "gaming", so
# matching the category means matching franchises.
_GAMING = re.compile(
    r"\b(video ?game|gaming|nintendo|playstation|ps5|xbox|steam ?deck|valve|"
    r"minecraft|roblox|fortnite|grand theft auto|gta ?\d?|elden ring|zelda|"
    r"mario|pok[eé]mon|call of duty|counter.?strike|valorant|league of legends|"
    r"dota|overwatch|apex legends|battlefield|assassin.s creed|cyberpunk 2077|"
    r"starfield|baldur.s gate|silksong|hollow knight|the sims|halo|"
    r"final fantasy|resident evil|rockstar games|ubisoft|bethesda|blizzard|"
    r"esports?|speedrun|twitch|nintendo switch|game awards)\b", re.I
)
_TECH = re.compile(
    r"\b(ai|model|chip|gpu|software|open.?source|linux|rust|python|database|"
    r"startup|browser|kernel|api|compiler|protocol)\b", re.I
)

# Wikipedia's most-read list is full of scaffolding pages that are not subjects.
_WIKI_NOISE = re.compile(
    r"^(main.page|special:|wikipedia:|portal:|category:|file:|talk:|"
    r"deaths in \d{4}|\d{4} in )", re.I
)


def _get_json(url):
    request = urllib.request.Request(url)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _cached(key, producer):
    now = time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < CACHE_TTL:
            return entry[1]
    try:
        value = producer()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        log.debug("trend source %s unavailable: %s", key, exc)
        with _lock:
            entry = _cache.get(key)
        return entry[1] if entry else []
    with _lock:
        _cache[key] = (now, value)
    return value


def _wikipedia_most_read():
    """Yesterday's most-read English Wikipedia articles."""
    # Yesterday, because today's feed is incomplete until the day closes.
    stamp = time.gmtime(time.time() - 86400)
    url = (
        "https://api.wikimedia.org/feed/v1/wikipedia/en/featured/%04d/%02d/%02d"
        % (stamp.tm_year, stamp.tm_mon, stamp.tm_mday)
    )
    data = _get_json(url)
    articles = (data.get("mostread") or {}).get("articles") or []

    subjects = []
    for article in articles:
        title = (article.get("titles") or {}).get("normalized") \
            or article.get("title") or ""
        title = title.replace("_", " ").strip()
        if not title or _WIKI_NOISE.match(title):
            continue
        subjects.append({
            "subject": title[:80],
            "source": "Wikipedia most-read",
            "url": (article.get("content_urls") or {}).get("desktop", {}).get("page"),
            "blurb": (article.get("extract") or "")[:240],
            "rank": len(subjects) + 1,
        })
        if len(subjects) >= 30:
            break
    return subjects


def _hacker_news():
    """Current top stories, for technology and internet culture."""
    ids = _get_json("https://hacker-news.firebaseio.com/v0/topstories.json")[:20]
    subjects = []
    for story_id in ids:
        try:
            item = _get_json(
                "https://hacker-news.firebaseio.com/v0/item/%d.json" % story_id
            )
        except Exception:  # noqa: BLE001 - one dead story is not a failure
            continue
        title = (item or {}).get("title")
        if not title:
            continue
        subjects.append({
            "subject": title[:110],
            "source": "Hacker News",
            "url": item.get("url")
                   or "https://news.ycombinator.com/item?id=%d" % story_id,
            "blurb": "",
            "rank": len(subjects) + 1,
        })
        if len(subjects) >= 15:
            break
    return subjects


def current(category="anything", *, limit=12):
    """Live subjects, newest cache first. Returns [] rather than raising."""
    wiki = _cached("wikipedia", _wikipedia_most_read)
    news = _cached("hackernews", _hacker_news)

    if category == "gaming":
        pool = [s for s in wiki + news if _GAMING.search(s["subject"])]
    elif category == "technology":
        pool = news + [s for s in wiki if _TECH.search(s["subject"])]
    elif category == "news":
        pool = wiki
    elif category == "culture":
        pool = [s for s in wiki if not _TECH.search(s["subject"])]
    else:
        pool = wiki + news

    # A narrow category is often empty on a given day -- nothing gaming-related
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

    return pool[:limit]


def pick(category="anything", *, rng=None, exclude=()):
    """One live subject, avoiding ones already used. None if nothing is available."""
    pool = [s for s in current(category, limit=40)
            if s["subject"] not in exclude]
    if not pool:
        return None
    return (rng or random).choice(pool)


def context(subject, *, max_chars=420):
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


def status():
    with _lock:
        return {
            key: {"count": len(value), "age_seconds": int(time.monotonic() - ts)}
            for key, (ts, value) in _cache.items()
        }
