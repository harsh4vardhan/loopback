"""Give bots what a video actually says about itself.

A transcript would be ideal and is not available: YouTube's timedtext endpoint
returns empty without signed parameters, and captions.list requires OAuth as
the video's owner. Scraping the watch page would work and is both against their
terms and permanently one markup change from breaking.

videos.list is the honest substitute, and it is better than the title by a wide
margin -- the uploader's own description, their tags, the duration, and the view
and like counts. All documented, and one quota unit against search's hundred,
so enriching a whole batch of results is effectively free.

  "Alexandria Ocasio Cortez is now the leading Democratic candidate for the
   2028 Presidential Election per Kalshi's latest forecasting prediction odds"
  tags: elections, politics, news   9s   925 views / 5 likes

A bot reacting to that is reacting to something real.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- discovery: enrich search results in one batched call -----------------
d = root / "loopback" / "discovery.py"
s = d.read_text(encoding="utf-8")

ENRICH = '''
def _youtube_details(video_ids):
    """Descriptions, tags and counts for up to 50 videos, in one call.

    A transcript is not obtainable for someone else's video without OAuth or
    scraping, so this is the closest legitimate thing: what the uploader wrote
    about it themselves. Costs 1 quota unit for the whole batch.
    """
    if not video_ids or not config.YOUTUBE_API_KEY:
        return {}

    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({
        "key": config.YOUTUBE_API_KEY,
        "id": ",".join(video_ids[:50]),
        "part": "snippet,contentDetails,statistics",
    })
    try:
        data = _get_json(url, source="youtube_details")
    except DiscoveryError as exc:
        log.debug("could not enrich youtube results: %s", exc)
        return {}

    details = {}
    for item in data.get("items", []):
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        description = " ".join((snippet.get("description") or "").split())
        details[item.get("id")] = {
            "description": description[:600],
            "tags": [t for t in (snippet.get("tags") or [])][:8],
            "duration": (item.get("contentDetails") or {}).get("duration", ""),
            "views": int(stats.get("viewCount") or 0),
            "likes": int(stats.get("likeCount") or 0),
        }
    return details


'''

s = s.replace("def _youtube(query, limit):", ENRICH.lstrip("\n") + "def _youtube(query, limit):", 1)

# Attach the details to each result before returning.
s = s.replace(
    '''        found.append({
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
    '''        found.append({
            # The Shorts URL, so links.normalise recognises the format and the
            # feed knows to let it fill the stage.
            "url": "https://www.youtube.com/shorts/%s" % video_id,
            "video_id": video_id,
            "title": (snippet.get("title") or query)[:180],
            "source": "YouTube Shorts",
            "page_url": "https://www.youtube.com/shorts/%s" % video_id,
            "license": "standard YouTube licence, embedded",
            "bytes": 0,
            "poster": poster,
            "channel": (snippet.get("channelTitle") or "")[:120],
        })

    # One extra call for the whole batch: the uploader's own description and
    # tags, which is the closest thing to knowing what is in the video.
    details = _youtube_details([item["video_id"] for item in found])
    for item in found:
        item.update(details.get(item["video_id"], {}))
    return found''',
)

s = s.replace(
    '''HOURLY_BUDGET = {
    "youtube": 4, "pexels": 120, "pixabay": 120, "nasa": 200, "wikimedia": 60,
}''',
    '''HOURLY_BUDGET = {
    # Search costs 100 units; the details lookup costs 1, so it gets its own
    # generous ceiling rather than competing with searches for the same budget.
    "youtube": 4, "youtube_details": 200,
    "pexels": 120, "pixabay": 120, "nasa": 200, "wikimedia": 60,
}''',
)

d.write_text(s, encoding="utf-8")
print("discovery.py: youtube results enriched with description, tags, counts")

# --- api: allow the new context fields through ----------------------------
a = root / "loopback" / "api.py"
s = a.read_text(encoding="utf-8")
s = s.replace(
    '''    "source_url", "license", "provider", "blurb", "category", "byline",''',
    '''    "source_url", "license", "provider", "blurb", "category", "byline",
    "description", "tags", "views", "duration",''',
)
# tags arrive as a list, which the scalar-only validator would drop.
s = s.replace(
    '''        if isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, str):''',
    '''        if isinstance(value, (int, float)):
            out[key] = value
        elif key == "tags" and isinstance(value, list):
            out[key] = [
                " ".join(str(t).split())[:40] for t in value[:8] if str(t).strip()
            ]
        elif isinstance(value, str):''',
)
a.write_text(s, encoding="utf-8")
print("api.py: description/tags/views accepted in context")

# --- runtime: record it, and hand it to whoever replies -------------------
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    '''                        context={
                            "subject": subject,
                            "blurb": _blurb_for(subject).get("blurb", ""),''',
    '''                        context={
                            "subject": subject,
                            # The uploader's own words about the clip. This is
                            # what a bot may legitimately react to, since it
                            # cannot watch anything.
                            "description": item.get("description", ""),
                            "tags": item.get("tags", []),
                            "views": item.get("views", 0),
                            "duration": item.get("duration", ""),
                            "blurb": _blurb_for(subject).get("blurb", ""),''',
)

s = s.replace(
    '''    context = post.get("context") or {}
    blurb = (context.get("blurb") or "").strip()
    source = (context.get("trend_source") or context.get("source") or "").strip()''',
    '''    context = post.get("context") or {}
    blurb = (context.get("blurb") or "").strip()
    source = (context.get("trend_source") or context.get("source") or "").strip()

    # What the uploader said about their own video beats anything inferred.
    described = (context.get("description") or "").strip()
    tags = context.get("tags") or []
    if described or tags:
        parts = ["\\n\\nThe post you are replying to is about: %s" % subject]
        if described:
            parts.append("The uploader describes it as: %s" % described[:400])
        if tags:
            parts.append("Its tags are: %s" % ", ".join(str(t) for t in tags[:8]))
        parts.append(
            "You still cannot see the video -- react to the subject, the "
            "description or the tags, never to imagined footage. %s"
            % trends.TOPIC_GUARDRAIL
        )
        return "\\n".join(parts)''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py: description recorded and used when replying")

# --- personas: the caption may use the description -------------------------
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    '''        title = (item.get("title") or "").strip()
        channel = (item.get("channel") or "").strip()
        topic = subject or title or "something"

        prompt = (
            "You are posting about: %s\\n"
            "The clip you are attaching is titled %r%s.\\n"
            "You have NOT watched it and cannot see it. Do not describe the "
            "footage, do not mention colours or objects or anything visible, "
            "and do not pretend to have viewed it. Write one line reacting to "
            "the subject and the title: what you make of it, what it reminds "
            "you of, what you want to know, what does not add up. %s"
            % (topic, title or topic,
               (" by %s" % channel) if channel else "", TOPIC_GUARDRAIL)
        )
        return write(prompt, "%s." % str(topic)[:110])''',
    '''        title = (item.get("title") or "").strip()
        channel = (item.get("channel") or "").strip()
        described = (item.get("description") or "").strip()
        tags = item.get("tags") or []
        topic = subject or title or "something"

        known = ["You are posting about: %s" % topic,
                 "The clip is titled %r%s."
                 % (title or topic, (" by %s" % channel) if channel else "")]
        if described:
            known.append("The uploader describes it as: %s" % described[:400])
        if tags:
            known.append("Its tags: %s" % ", ".join(str(t) for t in tags[:8]))

        prompt = (
            "\\n".join(known)
            + "\\nThat is everything you know. You have NOT watched it and "
              "cannot see it: do not describe the footage, do not mention "
              "colours or objects or anything visible, and do not pretend to "
              "have viewed it. Write one line reacting to what you do know -- "
              "the subject, the title, or the uploader's own description. %s"
            % TOPIC_GUARDRAIL
        )
        return write(prompt, "%s." % str(topic)[:110])''',
)

p.write_text(s, encoding="utf-8")
print("personas.py: caption may draw on the uploader's description")

for f, marker in ((d, "_youtube_details"), (a, '"description", "tags"'),
                  (r, "The uploader describes it as"),
                  (p, "the uploader's own description")):
    print("  %-14s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
