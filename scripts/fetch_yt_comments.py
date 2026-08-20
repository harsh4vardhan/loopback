"""Read real comments from the YouTube Shorts already in our feed.

commentThreads.list takes an API key and no OAuth for public videos, and costs
one quota unit against search's hundred, so this is cheap. Instagram has no
equivalent -- its Graph API only reaches accounts you manage -- so there is no
Instagram half to this.

The point is to look at how people actually write in comment sections before
inventing personas that imitate them. Guessing produces a caricature; reading a
few hundred real ones produces archetypes that exist.

    python3 scripts/fetch_yt_comments.py            # print a sample
    python3 scripts/fetch_yt_comments.py --json out.json
"""
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import config, db  # noqa: E402

UA = "Loopback/0.1 (research feed; contact via project repository)"
VIDEO_ID = re.compile(r"/shorts/([A-Za-z0-9_-]{11})|[?&]v=([A-Za-z0-9_-]{11})")


def video_ids_in_feed(limit=40):
    """Every YouTube video this platform has posted."""
    rows = db.query(
        """
        select p.media ->> 'url' as url
          from @schema.posts p
         where p.is_deleted = false
           and lower(coalesce(p.context ->> 'source', '')) like '%youtube%'
         order by p.created_at desc
         limit $1
        """,
        [limit],
    )
    ids = []
    for row in rows:
        match = VIDEO_ID.search(row["url"] or "")
        if match:
            found = match.group(1) or match.group(2)
            if found and found not in ids:
                ids.append(found)
    return ids


def comments_for(video_id, *, limit=40):
    """Top-level comments, ordered by relevance -- what people actually see."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads?" + \
        urllib.parse.urlencode({
            "key": config.YOUTUBE_API_KEY,
            "videoId": video_id,
            "part": "snippet",
            "maxResults": min(limit, 100),
            "order": "relevance",
            "textFormat": "plainText",
        })
    request = urllib.request.Request(url)
    request.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:160]
        # Comments disabled is a normal state, not a failure worth shouting about.
        return {"error": "%s %s" % (exc.code, detail)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}

    out = []
    for item in data.get("items", []):
        top = (((item.get("snippet") or {}).get("topLevelComment") or {})
               .get("snippet") or {})
        text = " ".join((top.get("textDisplay") or "").split())
        if not text:
            continue
        out.append({
            "text": text[:400],
            "likes": int(top.get("likeCount") or 0),
            "replies": int((item.get("snippet") or {}).get("totalReplyCount") or 0),
        })
    return {"comments": out}


def main():
    if not config.YOUTUBE_API_KEY:
        print("YOUTUBE_API_KEY is not set")
        return 1

    ids = video_ids_in_feed()
    print("videos posted to the feed: %d\n" % len(ids))

    collected = []
    for video_id in ids[:14]:
        result = comments_for(video_id, limit=40)
        if "error" in result:
            print("  %s  -- %s" % (video_id, result["error"][:70]))
            continue
        got = result["comments"]
        collected.extend(got)
        print("  %s  %d comments" % (video_id, len(got)))

    print("\ncollected %d comments total\n" % len(collected))

    collected.sort(key=lambda c: c["likes"], reverse=True)
    print("--- most-liked, which is what a comment section actually looks like ---")
    for c in collected[:60]:
        print("  %6d  %s" % (c["likes"], c["text"][:96]))

    if "--json" in sys.argv:
        index = sys.argv.index("--json")
        target = pathlib.Path(sys.argv[index + 1] if index + 1 < len(sys.argv)
                              else "var/yt_comments.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(collected, indent=1), encoding="utf-8")
        print("\nwrote %s" % target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
