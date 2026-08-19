"""Add YouTube as a discovery source.

Stock footage is generic by construction -- it is filmed to be reusable, which
is the opposite of what a feed about current events needs. YouTube has actual
footage of actual subjects, its Data API is documented and free, and embedding
is explicitly supported, which the feed already renders.

The quota is the constraint worth designing around: 10,000 units a day and a
search costs 100, so roughly 100 searches daily. With the six-hour result cache
and several usable results per search that is comfortable, but the hourly
ceiling is set low deliberately -- a runaway loop must not burn a day's quota in
twenty minutes.

TikTok and Instagram were considered and are not here. Neither offers a public
search API: TikTok's Research API is approval-gated to academic institutions and
its Display API only reaches the authorising account's own videos; Instagram's
Graph API likewise only reaches accounts you manage. The only way to "search"
either is scraping, which is against their terms and would break constantly.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- config ----------------------------------------------------------------
c = root / "loopback" / "config.py"
s = c.read_text(encoding="utf-8")
if "YOUTUBE_API_KEY" not in s:
    s = s.replace(
        "PEXELS_API_KEY = os.environ.get",
        '''# YouTube Data API v3. Free key from Google Cloud. This is the only one of the
# big platforms with a usable public search: TikTok and Instagram have none.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
# Restrict to videos that are embeddable, syndicated, and short enough to sit
# in a feed. "short" is under four minutes in the API's vocabulary.
YOUTUBE_DURATION = os.environ.get("YOUTUBE_DURATION", "short").strip()

PEXELS_API_KEY = os.environ.get''',
        1,
    )
    c.write_text(s, encoding="utf-8")
    print("config.py: YOUTUBE_API_KEY added")

# --- discovery -------------------------------------------------------------
d = root / "loopback" / "discovery.py"
s = d.read_text(encoding="utf-8")

YT = '''
# --- YouTube --------------------------------------------------------------

def _youtube(query, limit):
    """Real footage of the actual subject, embedded rather than downloaded.

    Only videos the uploader has allowed to be embedded and syndicated are
    requested, so nothing here is played somewhere its owner did not permit.
    """
    if not config.YOUTUBE_API_KEY:
        return []

    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode({
        "key": config.YOUTUBE_API_KEY,
        "q": query,
        "part": "snippet",
        "type": "video",
        "maxResults": max(5, min(limit * 2, 15)),
        "videoEmbeddable": "true",
        "videoSyndicated": "true",
        "videoDuration": config.YOUTUBE_DURATION,
        "safeSearch": "moderate",
        "relevanceLanguage": "en",
        "order": "relevance",
    })
    data = _get_json(url, source="youtube")

    found = []
    for item in data.get("items", [])[:limit]:
        video_id = ((item.get("id") or {}).get("videoId") or "").strip()
        snippet = item.get("snippet") or {}
        if not video_id:
            continue
        thumbnails = snippet.get("thumbnails") or {}
        poster = ((thumbnails.get("high") or thumbnails.get("medium")
                   or thumbnails.get("default") or {}).get("url"))
        found.append({
            "url": "https://www.youtube.com/watch?v=%s" % video_id,
            "title": (snippet.get("title") or query)[:180],
            "source": "YouTube",
            "page_url": "https://www.youtube.com/watch?v=%s" % video_id,
            "license": "standard YouTube licence, embedded",
            "bytes": 0,
            "poster": poster,
            "channel": (snippet.get("channelTitle") or "")[:120],
        })
    return found


'''

if "_youtube" not in s:
    s = s.replace("# --- Pexels ---", YT.lstrip("\n") + "# --- Pexels ---", 1)

s = s.replace(
    '''TOPICAL_SOURCES = {
    "pexels": _pexels,
    "pixabay": _pixabay,
    "nasa": _nasa,
}''',
    '''TOPICAL_SOURCES = {
    # Ordered by how well each answers "show me this specific thing". YouTube
    # has footage of the subject; the stock libraries have footage that merely
    # suits it; NASA has neither unless the subject is space.
    "youtube": _youtube,
    "pexels": _pexels,
    "pixabay": _pixabay,
    "nasa": _nasa,
}''',
)

s = s.replace(
    '''HOURLY_BUDGET = {"pexels": 120, "pixabay": 120, "nasa": 200, "wikimedia": 60}''',
    '''# YouTube's free quota is 10,000 units a day and a search costs 100, so about
# 100 searches daily. Four an hour leaves headroom and makes it impossible for a
# loop to burn the day's allowance before anyone notices.
HOURLY_BUDGET = {
    "youtube": 4, "pexels": 120, "pixabay": 120, "nasa": 200, "wikimedia": 60,
}''',
)

s = s.replace(
    '''def configured():
    """Which topical sources actually have what they need to run."""
    live = ["nasa"]
    if config.PEXELS_API_KEY:
        live.append("pexels")
    if config.PIXABAY_API_KEY:
        live.append("pixabay")
    return live''',
    '''def configured():
    """Which topical sources actually have what they need to run."""
    live = ["nasa"]
    if config.YOUTUBE_API_KEY:
        live.append("youtube")
    if config.PEXELS_API_KEY:
        live.append("pexels")
    if config.PIXABAY_API_KEY:
        live.append("pixabay")
    return live''',
)

# YouTube should be tried first when it is available, rather than shuffled in.
s = s.replace(
    '''    if sources:
        names = [name for name in sources if name in SOURCES]
    else:
        names = list(TOPICAL_SOURCES)
        if browse:
            names += list(BROWSE_SOURCES)''',
    '''    if sources:
        names = [name for name in sources if name in SOURCES]
    else:
        names = list(TOPICAL_SOURCES)
        if browse:
            names += list(BROWSE_SOURCES)
        # Try YouTube first when it is configured: it is the only source with
        # footage of the subject rather than footage that merely suits it. The
        # shuffle below would otherwise bury it behind the stock libraries.
        if "youtube" in names and config.YOUTUBE_API_KEY:
            names.remove("youtube")
            names.insert(0, "youtube")
            (rng or random).shuffle(names[1:])
            return _collect(names, query, limit, first_fixed=True)''',
)

# A small helper so the fixed-first ordering does not duplicate the loop body.
s = s.replace(
    '''    results = []
    for name in names:
        key = (name, query.lower(), limit)''',
    '''    return _collect(names, query, limit)


def _collect(names, query, limit, first_fixed=False):
    """Ask each source in order until enough results are gathered."""
    results = []
    for name in names:
        key = (name, query.lower(), limit)''',
)

s = s.replace(
    '''    names = [name for name in (sources or SOURCES) if name in SOURCES]
    if not names:
        return []
    (rng or random).shuffle(names)''',
    '''    if not names:
        return []
    if not first_fixed:
        (rng or random).shuffle(names)''',
)

d.write_text(s, encoding="utf-8")
print("discovery.py: YouTube source added")

for marker in ("_youtube", '"youtube": 4', "def _collect"):
    print("  %-18s %s" % (marker, "present" if marker in s else "MISSING"))
