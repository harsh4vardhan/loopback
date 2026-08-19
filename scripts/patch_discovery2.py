"""Second discovery patch, written against what the live APIs actually do.

Findings from probing:
  * NASA searches by topic and returns relevant, public-domain mp4. Keep it as
    the topical source.
  * Wikimedia Commons honours `filetype:video` on its own, but combining that
    filter with a free-text term returns zero every time. It cannot do topical
    search, so it becomes a serendipity source instead of being deleted.
  * archive.org's advancedsearch returned results early on and now returns zero
    for every query including ones that previously worked, which is rate
    limiting rather than a bad query. It stays in the file but off by default.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "discovery.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    '''Three sources, chosen because each has a documented public JSON API meant for
programmatic use and serves openly licensed material. No scraping, no keys, and
nothing here touches a site that would rather we did not:

  * Internet Archive -- public domain and openly licensed film
  * Wikimedia Commons -- free-licence video, mostly CC BY-SA
  * NASA -- public domain
''',
    '''Sources have documented public JSON APIs meant for programmatic use and serve
openly licensed material. No scraping, no keys, and nothing here touches a site
that would rather we did not. They do not all do the same job:

  * NASA (public domain) -- searches by topic and returns relevant footage.
    This is the one a bot uses when it is looking for something specific.
  * Wikimedia Commons (free licence) -- its search honours `filetype:video`
    alone, but returns nothing whenever that filter is combined with a search
    term, so it cannot answer a topical query. It is wired as a serendipity
    source: a bot browsing rather than searching.
  * Internet Archive -- worked initially and then began returning zero for
    every query, including ones that had just succeeded, which reads as rate
    limiting. Left in place but disabled by default; set ARCHIVE_ENABLED to
    try it again.
''',
)

s = s.replace(
    '''SOURCES = {
    "archive": _archive,
    "wikimedia": _wikimedia,
    "nasa": _nasa,
}''',
    '''def _wikimedia_browse(_query, limit):
    """Recent video on Commons, ignoring the topic.

    `filetype:video` cannot be combined with a search term here, so this does
    not pretend to be a search. A bot using it is browsing.
    """
    return _wikimedia_raw("filetype:video", limit)


# Sources that can actually answer "find me video about X".
TOPICAL_SOURCES = {
    "nasa": _nasa,
}

# Sources that return video but cannot be aimed at a subject.
BROWSE_SOURCES = {
    "wikimedia": _wikimedia_browse,
}

# Kept for the record; see the module docstring.
ARCHIVE_ENABLED = False

SOURCES = dict(TOPICAL_SOURCES)
SOURCES.update(BROWSE_SOURCES)
if ARCHIVE_ENABLED:
    SOURCES["archive"] = _archive''',
)

# _wikimedia becomes a raw helper taking a full search string.
s = s.replace(
    '''def _wikimedia(query, limit):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": "filetype:video %s" % query,''',
    '''def _wikimedia_raw(search, limit):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": search,''',
)

# search() should try topical first and only then browse.
s = s.replace(
    '''def search(query, *, limit=5, sources=None, rng=None):
    """Find playable video for a topic. Returns a list, possibly empty.

    Never raises: a bot's turn must not fail because a catalogue was down.
    """
    query = " ".join(str(query or "").split())[:120]
    if not query:
        return []

    names = [name for name in (sources or SOURCES) if name in SOURCES]''',
    '''def search(query, *, limit=5, sources=None, rng=None, browse=True):
    """Find playable video for a topic. Returns a list, possibly empty.

    Topical sources are asked first. `browse` allows falling back to sources
    that return video but ignore the subject -- useful for a bot that would
    rather post something unrelated than nothing.

    Never raises: a bot's turn must not fail because a catalogue was down.
    """
    query = " ".join(str(query or "").split())[:120]
    if not query:
        return []

    if sources:
        names = [name for name in sources if name in SOURCES]
    else:
        names = list(TOPICAL_SOURCES)
        if browse:
            names += list(BROWSE_SOURCES)''',
)
p.write_text(s, encoding="utf-8")
print("discovery.py patched (second pass)")
for marker in ("TOPICAL_SOURCES", "BROWSE_SOURCES", "_wikimedia_raw",
               "ARCHIVE_ENABLED"):
    print("  %-18s %s" % (marker, "present" if marker in s else "MISSING"))
