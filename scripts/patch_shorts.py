"""Take only YouTube Shorts, and let them fill the stage.

A regular YouTube video is 16:9 and has to be letterboxed into a 9:16 feed,
which looks like a mistake. Shorts are already vertical, so they fit the stage
exactly and sit alongside the Pexels clips without anything looking wrong.

The Data API has no "Shorts only" filter, so this does two things: biases the
query toward them, then verifies each candidate. A Short's canonical URL,
/shorts/<id>, serves a page directly; anything that is not a Short redirects to
/watch. That check costs one cheap request per candidate and no API quota, and
it is the only way to be sure rather than hopeful.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- discovery -------------------------------------------------------------
d = root / "loopback" / "discovery.py"
s = d.read_text(encoding="utf-8")

s = s.replace(
    '''def _youtube(query, limit):
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
    return found''',
    '''class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop urllib following redirects, so one can be detected."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_no_redirect_opener = urllib.request.build_opener(_NoRedirect)


def _is_short(video_id):
    """True when this id is a Short.

    /shorts/<id> serves a page for a Short and redirects to /watch for anything
    else. The API exposes no flag for this, so the redirect is the signal. Costs
    no API quota.
    """
    request = urllib.request.Request(
        "https://www.youtube.com/shorts/%s" % video_id, method="HEAD"
    )
    request.add_header("User-Agent", USER_AGENT)
    try:
        with _no_redirect_opener.open(request, timeout=10) as response:
            return response.status == 200
    except urllib.error.HTTPError as exc:
        # 3xx surfaces here because redirects are refused: not a Short.
        return exc.code == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        # Unreachable: assume not, rather than posting a landscape clip into a
        # vertical feed on a guess.
        return False


def _youtube(query, limit):
    """Vertical footage of the actual subject, embedded rather than downloaded.

    Shorts only: they are natively 9:16 and fill the stage, where a regular
    video would have to be letterboxed and look broken. Only videos the uploader
    has allowed to be embedded and syndicated are requested, so nothing is
    played anywhere its owner did not permit.
    """
    if not config.YOUTUBE_API_KEY:
        return []

    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode({
        "key": config.YOUTUBE_API_KEY,
        # The API has no Shorts filter; "#shorts" is how they are actually
        # labelled, and the duration bound removes most of what is left.
        "q": "%s #shorts" % query,
        "part": "snippet",
        "type": "video",
        "maxResults": max(8, min(limit * 4, 20)),
        "videoEmbeddable": "true",
        "videoSyndicated": "true",
        "videoDuration": "short",
        "safeSearch": "moderate",
        "relevanceLanguage": "en",
        "order": "relevance",
    })
    data = _get_json(url, source="youtube")

    found = []
    for item in data.get("items", []):
        if len(found) >= limit:
            break
        video_id = ((item.get("id") or {}).get("videoId") or "").strip()
        snippet = item.get("snippet") or {}
        if not video_id or not _is_short(video_id):
            continue
        thumbnails = snippet.get("thumbnails") or {}
        poster = ((thumbnails.get("high") or thumbnails.get("medium")
                   or thumbnails.get("default") or {}).get("url"))
        found.append({
            # The Shorts URL, so links.normalise recognises the format and the
            # feed knows to let it fill the stage.
            "url": "https://www.youtube.com/shorts/%s" % video_id,
            "title": (snippet.get("title") or query)[:180],
            "source": "YouTube Shorts",
            "page_url": "https://www.youtube.com/shorts/%s" % video_id,
            "license": "standard YouTube licence, embedded",
            "bytes": 0,
            "poster": poster,
            "channel": (snippet.get("channelTitle") or "")[:120],
        })
    return found''',
)

d.write_text(s, encoding="utf-8")
print("discovery.py: Shorts only")

# --- links: mark a Short as vertical --------------------------------------
lk = root / "loopback" / "links.py"
s = lk.read_text(encoding="utf-8")

s = s.replace(
    '''    if host in _YOUTUBE_HOSTS:
        video_id = _youtube_id(parsed)
        if video_id:
            payload.update({
                "provider": "youtube",
                "render": "iframe",''',
    '''    if host in _YOUTUBE_HOSTS:
        video_id = _youtube_id(parsed)
        if video_id:
            payload.update({
                "provider": "youtube",
                "render": "iframe",
                # A Short is already 9:16, so the feed lets it fill the stage
                # instead of letterboxing it like a normal 16:9 player.
                "vertical": parsed.path.startswith("/shorts/"),''',
)

lk.write_text(s, encoding="utf-8")
print("links.py: vertical flag for Shorts")

# --- frontend: fill the stage, and credit the uploader --------------------
a = root / "static" / "app.js"
s = a.read_text(encoding="utf-8")

s = s.replace(
    """      frame.setAttribute('loading', 'lazy');
      container.appendChild(frame);""",
    """      frame.setAttribute('loading', 'lazy');
      /* A Short is natively 9:16, so it fills the stage. Anything else is a
         16:9 player and gets centred against black rather than distorted. */
      if (media.vertical) frame.classList.add('is-vertical');
      container.appendChild(frame);""",
)

s = s.replace(
    """    if (ctx.source) {
      var src = el('span', 'poweredby', ctx.source);
      src.title = ctx.license ? 'licence: ' + ctx.license : 'footage source';
      stamp.appendChild(document.createTextNode(' '));
      stamp.appendChild(src);
    }""",
    """    if (ctx.source) {
      var src = el('span', 'poweredby', ctx.source);
      src.title = ctx.license ? 'licence: ' + ctx.license : 'footage source';
      stamp.appendChild(document.createTextNode(' '));
      stamp.appendChild(src);
    }
    /* Embedded work belongs to whoever made it, and should say so. */
    if (ctx.byline) {
      var by = el('span', 'byline', 'by ' + ctx.byline);
      by.title = 'the creator whose video this is';
      stamp.appendChild(document.createTextNode(' '));
      stamp.appendChild(by);
    }""",
)

a.write_text(s, encoding="utf-8")
print("app.js: vertical embeds and uploader credit")

for f, marker in ((d, "_is_short"), (lk, '"vertical"'), (a, "is-vertical")):
    print("  %-14s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
