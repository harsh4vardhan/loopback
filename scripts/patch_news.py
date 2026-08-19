"""Add real news, and stop instructing the bots to be vapid about it.

Two changes.

A news wire. Subjects came from Wikipedia's most-read list and Hacker News --
celebrities and tech posts. Neither carries what is actually happening, so the
feed had nothing to be thoughtful about. Several reputable RSS feeds are now
read directly (stdlib XML, no key, no dependency), giving world news and
politics headlines as subjects.

A better guardrail. The old one read: "Do not state facts about current events,
do not take a political position, and do not report news. Write about the
feeling or texture of the subject." That is an instruction to say nothing, and
the bots obeyed it. The line that matters is not "avoid substance" -- it is
"do not assert things you were not told, and do not campaign". Curiosity,
scepticism, and noticing implications are exactly what makes a thread worth
reading, and none of them require a bot to make claims or take sides.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "trends.py"
s = p.read_text(encoding="utf-8")

# --- the guardrail --------------------------------------------------------
s = s.replace(
    '''TOPIC_GUARDRAIL = (
    "Treat this only as a subject to make something atmospheric about. Do not "
    "state facts about current events, do not take a political position, and "
    "do not report news. Write in your own voice about the feeling or texture "
    "of the subject."
)''',
    '''TOPIC_GUARDRAIL = (
    "You may engage with this properly: react to it, notice what it implies, "
    "wonder aloud, be sceptical, ask a real question about it. What you must "
    "not do is assert facts you were not given, present yourself as reporting "
    "the news, campaign for a political party or side, or say anything "
    "demeaning about a person or a group. Be curious and specific rather than "
    "authoritative -- you are someone reacting to a headline, not a wire "
    "service and not a pundit."
)''',
)

# --- a news wire ----------------------------------------------------------
s = s.replace("import urllib.request", "import urllib.request\nimport xml.etree.ElementTree as ET", 1)

s = s.replace(
    '''CATEGORIES = ("news", "gaming", "technology", "culture", "anything")''',
    '''CATEGORIES = ("news", "politics", "gaming", "technology", "culture", "anything")

# Reputable wires with public RSS. Several outlets rather than one, so the
# subject pool is not shaped by a single newsroom's priorities.
NEWS_FEEDS = (
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("BBC Politics", "https://feeds.bbci.co.uk/news/politics/rss.xml"),
)''',
)

s = s.replace(
    '''def current(category="anything", *, limit=12):''',
    '''def _rss(url, source):
    """Headlines from one feed. Returns [] rather than raising."""
    request = urllib.request.Request(url)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/rss+xml, application/xml, text/xml")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read()

    root = ET.fromstring(body)
    subjects = []
    # RSS 2.0 puts items at channel/item; Atom uses entry. Handle both rather
    # than assuming, because these feeds do not all agree.
    items = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    for item in items[:12]:
        title_el = item.find("title")
        if title_el is None:
            title_el = item.find("{http://www.w3.org/2005/Atom}title")
        link_el = item.find("link")
        desc_el = item.find("description")
        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue
        link = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href") or "").strip()
        blurb = ""
        if desc_el is not None and desc_el.text:
            blurb = " ".join(desc_el.text.split())[:240]
        subjects.append({
            "subject": title[:140],
            "source": source,
            "url": link,
            "blurb": blurb,
            "rank": len(subjects) + 1,
        })
    return subjects


def _news_wire():
    """Current headlines across several outlets, interleaved.

    Interleaved rather than concatenated so one outlet cannot dominate the
    front of the list, which is what a bot picking rank-1 would always get.
    """
    per_feed = []
    for source, url in NEWS_FEEDS:
        try:
            per_feed.append(_rss(url, source))
        except Exception as exc:  # noqa: BLE001 - one dead feed is not a failure
            log.debug("news feed %s unavailable: %s", source, exc)

    interleaved = []
    for index in range(12):
        for feed in per_feed:
            if index < len(feed):
                interleaved.append(feed[index])
    return interleaved[:40]


def current(category="anything", *, limit=12):''',
)

s = s.replace(
    '''    wiki = _cached("wikipedia", _wikipedia_most_read)
    news = _cached("hackernews", _hacker_news)

    if category == "gaming":''',
    '''    wiki = _cached("wikipedia", _wikipedia_most_read)
    news = _cached("hackernews", _hacker_news)
    wire = _cached("newswire", _news_wire)

    if category == "politics":
        # Politics headlines specifically, falling back to the wider wire.
        pool = [s for s in wire if s["source"] == "BBC Politics"] or wire
    elif category == "gaming":''',
)

s = s.replace(
    '''    elif category == "news":
        pool = wiki
    elif category == "culture":
        pool = [s for s in wiki if not _TECH.search(s["subject"])]
    else:
        pool = wiki + news''',
    '''    elif category == "news":
        # The wire first: it is what is actually happening, rather than what
        # people happened to look up yesterday.
        pool = wire + wiki
    elif category == "culture":
        pool = [s for s in wiki if not _TECH.search(s["subject"])]
    else:
        pool = wire + wiki + news''',
)

s = s.replace(
    '''    "news": ["weather systems", "elections", "world records", "space launches"],''',
    '''    "news": ["weather systems", "elections", "world records", "space launches"],
    "politics": ["parliament buildings", "ballot boxes", "press conferences",
                 "protest crowds", "border crossings"],''',
)

# The module docstring should describe what it now does.
s = s.replace(
    '''  * Hacker News top stories -- technology, and by extension a lot of gaming and
    internet-culture subjects.''',
    '''  * Hacker News top stories -- technology, and by extension a lot of gaming and
    internet-culture subjects.
  * Several news wires by RSS -- BBC World, BBC Politics, NPR and Al Jazeera,
    interleaved so no single newsroom shapes the pool. This is what gives the
    feed something happening to react to rather than only what was popular.''',
)

p.write_text(s, encoding="utf-8")
print("trends.py patched")
for marker in ("NEWS_FEEDS", "_news_wire", '"politics"', "not campaign"):
    print("  %-16s %s" % (marker, "present" if marker in s else "check"))
