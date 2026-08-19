"""Finding real video on the open web.

A bot that can only draw its own clips eventually repeats itself. This module
lets one go and look for footage instead, then post it as a `link`.

Sources have documented public JSON APIs meant for programmatic use and serve
openly licensed material. No scraping, no keys, and nothing here touches a site
that would rather we did not. They do not all do the same job:

  * NASA (public domain) -- searches by topic and returns relevant footage.
    This is the one a bot uses when it is looking for something specific.
  * Wikimedia Commons (free licence) -- its search honours `filetype:video`
    alone, but returns nothing whenever that filter is combined with a search
    term, so it cannot answer a topical query. It is wired as a serendipity
    source: a bot browsing rather than searching.
  * Pexels and Pixabay (free keys) -- direct mp4 for essentially any subject.
    These are what make a topical feed possible; without one of them the feed
    is limited to what NASA happens to have filmed.

archive.org was removed: both its advancedsearch and its newer scrape endpoint
return total=0 for every query from this host, including queries that had just
succeeded, so it is refusing traffic rather than failing.

Results are cached in-process and every source is rate limited, because the
polite thing and the cheap thing are the same thing here.
"""
import json
import logging
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger("loopback.discovery")

USER_AGENT = (
    "Loopback/0.1 (a research feed of machine-authored short video; "
    "contact via the project repository)"
)

TIMEOUT = 20
CACHE_TTL = 1800          # half an hour; these catalogues do not move fast
MIN_SECONDS_BETWEEN = 3.0  # per source

_cache = {}
_cache_lock = threading.Lock()
_last_call = {}
_rate_lock = threading.Lock()

# Formats that actually play inline in a current browser. Theora (.ogv) is
# excluded: Chrome dropped support, so those results would be dead frames.
VIDEO_EXTENSIONS = (".mp4", ".webm", ".m4v")

# A feed autoplays whatever is on screen, so a 400MB master scan is not a
# candidate no matter how relevant it is.
MAX_BYTES = 60_000_000
MIN_BYTES = 150_000


class DiscoveryError(RuntimeError):
    """A source could not be reached or returned nothing usable."""


def _safe_url(url):
    """Percent-encode a path that a catalogue handed back unencoded."""
    parts = urllib.parse.urlsplit(str(url))
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc,
        urllib.parse.quote(parts.path, safe="/%"),
        urllib.parse.quote(parts.query, safe="=&%"), parts.fragment,
    ))


def _throttle(source):
    """Never hit one source faster than MIN_SECONDS_BETWEEN."""
    with _rate_lock:
        last = _last_call.get(source, 0.0)
        wait = MIN_SECONDS_BETWEEN - (time.monotonic() - last)
        if wait > 0:
            time.sleep(min(wait, MIN_SECONDS_BETWEEN))
        _last_call[source] = time.monotonic()


def _get_json(url, *, source):
    _throttle(source)
    request = urllib.request.Request(_safe_url(url))
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise DiscoveryError("%s HTTP %s" % (source, exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DiscoveryError("%s unreachable: %s" % (source, exc)) from exc
    except json.JSONDecodeError as exc:
        raise DiscoveryError("%s returned non-JSON: %s" % (source, exc)) from exc


# --- Wikimedia Commons ----------------------------------------------------

def _wikimedia_raw(search, limit):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": search,
        "gsrnamespace": 6,
        "gsrlimit": max(3, limit * 3),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    })
    data = _get_json(url, source="wikimedia")
    pages = ((data.get("query") or {}).get("pages")) or {}

    found = []
    for page in pages.values():
        if len(found) >= limit:
            break
        info = (page.get("imageinfo") or [{}])[0]
        media_url = info.get("url") or ""
        if not media_url.lower().endswith(VIDEO_EXTENSIONS):
            continue
        if int(info.get("size") or 0) > MAX_BYTES:
            continue
        extra = info.get("extmetadata") or {}
        found.append({
            "url": media_url,
            "title": str(page.get("title", "")).replace("File:", "")[:180],
            "source": "Wikimedia Commons",
            "page_url": info.get("descriptionurl") or media_url,
            "license": (extra.get("LicenseShortName") or {}).get("value", "CC"),
            "bytes": int(info.get("size") or 0),
        })
    return found


# --- NASA -----------------------------------------------------------------

def _nasa(query, limit):
    url = "https://images-api.nasa.gov/search?" + urllib.parse.urlencode({
        "q": query, "media_type": "video",
    })
    data = _get_json(url, source="nasa")
    items = ((data.get("collection") or {}).get("items")) or []

    found = []
    for item in items:
        if len(found) >= limit:
            break
        collection_url = item.get("href")
        meta = (item.get("data") or [{}])[0]
        if not collection_url:
            continue
        try:
            assets = _get_json(collection_url, source="nasa")
        except DiscoveryError:
            continue
        if not isinstance(assets, list):
            continue

        # Asset lists carry several renditions; the small one is the one a feed
        # should be loading.
        mp4s = [a for a in assets if str(a).lower().endswith(".mp4")]
        preferred = (
            next((a for a in mp4s if "~small" in a), None)
            or next((a for a in mp4s if "~mobile" in a), None)
            or (mp4s[0] if mp4s else None)
        )
        if not preferred:
            continue
        found.append({
            "url": preferred.replace("http://", "https://"),
            "title": (meta.get("title") or "NASA footage")[:180],
            "source": "NASA",
            "page_url": "https://images.nasa.gov/details/%s"
                        % meta.get("nasa_id", ""),
            "license": "public domain",
            "bytes": 0,
        })
    return found


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
        chosen = next((f for f in files if 700 <= (f.get("height") or 0) <= 1400), None) \
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


def _wikimedia_browse(_query, limit):
    """Recent video on Commons, ignoring the topic.

    `filetype:video` cannot be combined with a search term here, so this does
    not pretend to be a search. A bot using it is browsing.
    """
    return _wikimedia_raw("filetype:video", limit)


# Sources that can actually answer "find me video about X". Ordered by how
# broad their catalogue is: the stock libraries cover any subject, NASA covers
# space and earth science very well and nothing else at all.
TOPICAL_SOURCES = {
    "pexels": _pexels,
    "pixabay": _pixabay,
    "nasa": _nasa,
}

# Sources that return video but cannot be aimed at a subject.
BROWSE_SOURCES = {
    "wikimedia": _wikimedia_browse,
}

SOURCES = dict(TOPICAL_SOURCES)
SOURCES.update(BROWSE_SOURCES)


def configured():
    """Which topical sources actually have what they need to run."""
    live = ["nasa"]
    if config.PEXELS_API_KEY:
        live.append("pexels")
    if config.PIXABAY_API_KEY:
        live.append("pixabay")
    return live


# --- public interface -----------------------------------------------------

def search(query, *, limit=5, sources=None, rng=None, browse=True):
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
            names += list(BROWSE_SOURCES)
    if not names:
        return []
    (rng or random).shuffle(names)

    results = []
    for name in names:
        key = (name, query.lower(), limit)
        with _cache_lock:
            entry = _cache.get(key)
            if entry and time.monotonic() - entry[0] < CACHE_TTL:
                results.extend(entry[1])
                continue

        try:
            found = SOURCES[name](query, limit)
        except DiscoveryError as exc:
            log.debug("discovery via %s failed for %r: %s", name, query, exc)
            found = []
        except Exception:  # noqa: BLE001 - a source must never break a tick
            log.exception("discovery via %s raised for %r", name, query)
            found = []

        with _cache_lock:
            _cache[key] = (time.monotonic(), found)
            if len(_cache) > 500:
                _cache.clear()
        results.extend(found)

        if len(results) >= limit:
            break

    return results[:limit]


def pick(query, *, rng, exclude=()):
    """One result for a topic, avoiding URLs already posted. None if nothing."""
    candidates = [
        item for item in search(query, limit=6, rng=rng)
        if item["url"] not in exclude
    ]
    return rng.choice(candidates) if candidates else None


def cache_stats():
    with _cache_lock:
        return {"entries": len(_cache), "sources": sorted(SOURCES)}
