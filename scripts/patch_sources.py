"""Make real footage the default, and add the stock-video sources.

archive.org is removed: both its advancedsearch and its scrape endpoint now
return total=0 for every query from here, so it is refusing us rather than
failing. Pexels and Pixabay take its place -- both are free, both return
direct mp4 that plays inline, and both actually cover the subjects people
care about, which NASA does not.

Neither is enabled without a key, so the file is inert until one is set.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- config ---------------------------------------------------------------
c = root / "loopback" / "config.py"
s = c.read_text(encoding="utf-8")
if "PEXELS_API_KEY" not in s:
    s = s.replace(
        "# --- llm providers ---",
        '''# --- video discovery --------------------------------------------------------
# Free stock-video libraries. Both need a key, but neither charges: they are
# what makes a topical feed possible, since the openly licensed catalogues
# either have no footage of a given subject or refuse programmatic access.
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()


# --- llm providers ---''',
        1,
    )
    c.write_text(s, encoding="utf-8")
    print("config.py: added PEXELS_API_KEY / PIXABAY_API_KEY")

# --- discovery ------------------------------------------------------------
d = root / "loopback" / "discovery.py"
s = d.read_text(encoding="utf-8")

s = s.replace("import urllib.request", "import urllib.request\n\nfrom . import config", 1)

NEW_SOURCES = '''
# --- Pexels ---------------------------------------------------------------

def _pexels(query, limit):
    """Free stock video. Vertical orientation, which is what this feed wants."""
    if not config.PEXELS_API_KEY:
        return []
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({
        "query": query, "per_page": max(5, limit * 2),
        "orientation": "portrait", "size": "medium",
    })
    request = urllib.request.Request(_safe_url(url))
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Authorization", config.PEXELS_API_KEY)
    _throttle("pexels")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise DiscoveryError("pexels HTTP %s" % exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError,
            json.JSONDecodeError) as exc:
        raise DiscoveryError("pexels unreachable: %s" % exc) from exc

    found = []
    for video in data.get("videos", [])[:limit]:
        # Prefer an HD-but-not-huge rendition; a feed autoplays these.
        files = sorted(
            (f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4"),
            key=lambda f: (f.get("height") or 0),
        )
        chosen = next((f for f in files if 700 <= (f.get("height") or 0) <= 1400), None) \\
            or (files[-1] if files else None)
        if not chosen or not chosen.get("link"):
            continue
        found.append({
            "url": chosen["link"],
            "title": (video.get("alt") or "untitled")[:180],
            "source": "Pexels",
            "page_url": video.get("url"),
            "license": "Pexels licence",
            "bytes": 0,
            "poster": (video.get("video_pictures") or [{}])[0].get("picture"),
        })
    return found


# --- Pixabay --------------------------------------------------------------

def _pixabay(query, limit):
    """Free stock video, broader and sillier than Pexels. Good for variety."""
    if not config.PIXABAY_API_KEY:
        return []
    url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode({
        "key": config.PIXABAY_API_KEY, "q": query,
        "per_page": max(5, min(limit * 3, 50)), "safesearch": "true",
    })
    data = _get_json(url, source="pixabay")

    found = []
    for hit in data.get("hits", [])[:limit]:
        streams = hit.get("videos") or {}
        chosen = streams.get("medium") or streams.get("small") or streams.get("tiny")
        if not chosen or not chosen.get("url"):
            continue
        found.append({
            "url": chosen["url"],
            "title": (hit.get("tags") or "untitled")[:180],
            "source": "Pixabay",
            "page_url": hit.get("pageURL"),
            "license": "Pixabay licence",
            "bytes": int(chosen.get("size") or 0),
        })
    return found


'''

s = s.replace("def _wikimedia_browse(_query, limit):", NEW_SOURCES.lstrip("\n") + "def _wikimedia_browse(_query, limit):", 1)

s = s.replace(
    '''# Sources that can actually answer "find me video about X".
TOPICAL_SOURCES = {
    "nasa": _nasa,
}''',
    '''# Sources that can actually answer "find me video about X". Ordered by how
# broad their catalogue is: the stock libraries cover any subject, NASA covers
# space and earth science very well and nothing else at all.
TOPICAL_SOURCES = {
    "pexels": _pexels,
    "pixabay": _pixabay,
    "nasa": _nasa,
}''',
)

s = s.replace(
    '''# Kept for the record; see the module docstring.
ARCHIVE_ENABLED = False

SOURCES = dict(TOPICAL_SOURCES)
SOURCES.update(BROWSE_SOURCES)
if ARCHIVE_ENABLED:
    SOURCES["archive"] = _archive''',
    '''SOURCES = dict(TOPICAL_SOURCES)
SOURCES.update(BROWSE_SOURCES)


def configured():
    """Which topical sources actually have what they need to run."""
    live = ["nasa"]
    if config.PEXELS_API_KEY:
        live.append("pexels")
    if config.PIXABAY_API_KEY:
        live.append("pixabay")
    return live''',
)

# Drop the dead archive implementation entirely.
start = s.find("# --- Internet Archive ---")
end = s.find("# --- Wikimedia Commons ---")
if start != -1 and end != -1:
    s = s[:start] + s[end:]

s = s.replace(
    '''  * Internet Archive -- worked initially and then began returning zero for
    every query, including ones that had just succeeded, which reads as rate
    limiting. Left in place but disabled by default; set ARCHIVE_ENABLED to
    try it again.
''',
    '''  * Pexels and Pixabay (free keys) -- direct mp4 for essentially any subject.
    These are what make a topical feed possible; without one of them the feed
    is limited to what NASA happens to have filmed.

archive.org was removed: both its advancedsearch and its newer scrape endpoint
return total=0 for every query from this host, including queries that had just
succeeded, so it is refusing traffic rather than failing.
''',
)

d.write_text(s, encoding="utf-8")
print("discovery.py: archive removed, pexels + pixabay added")

# --- personas: real footage over procedural cards --------------------------
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    """    # Going out to the open web, finding real footage about a subject, and
    # posting it as a link.
    forage_chance = 0.07""",
    """    # Going out to the open web, finding real footage about a subject, and
    # posting it as a link. This is deliberately far higher than post_chance:
    # found footage is the interesting content, and the procedural clips work
    # better as punctuation than as the substance of the feed.
    forage_chance = 0.55""",
)

# Scene posting becomes the exception rather than the rule.
for old, new in (
    ("    post_chance = 0.16\n", "    post_chance = 0.05\n"),
    ("    post_chance = 0.12\n", "    post_chance = 0.05\n"),
    ("    post_chance = 0.14\n", "    post_chance = 0.05\n"),
    ("    post_chance = 0.13\n", "    post_chance = 0.04\n"),
    ("    post_chance = 0.22\n", "    post_chance = 0.06\n"),
):
    s = s.replace(old, new, 1)

for old, new in (
    ("    forage_chance = 0.10\n", "    forage_chance = 0.60\n"),
    ("    forage_chance = 0.05\n", "    forage_chance = 0.45\n"),
    ("    forage_chance = 0.09\n", "    forage_chance = 0.55\n"),
    ("    forage_chance = 0.08\n", "    forage_chance = 0.55\n"),
    ("    forage_chance = 0.14\n", "    forage_chance = 0.70\n"),
):
    s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")
print("personas.py: forage now dominates scene posting")

# --- stats should report the provider mix, not one model -------------------
a = root / "loopback" / "api.py"
s = a.read_text(encoding="utf-8")
s = s.replace(
    '''    payload["llm"] = config.ANTHROPIC_MODEL if config.llm_enabled() else None''',
    '''    from . import discovery, llm
    payload["llm"] = llm.status()
    payload["discovery"] = {"sources": discovery.configured()}''',
)
a.write_text(s, encoding="utf-8")
print("api.py: stats reports the provider mix and live sources")
