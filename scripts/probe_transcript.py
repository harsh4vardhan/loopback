"""What can we legitimately learn about a YouTube video we did not upload?

Three candidates, in order of preference:

  1. videos.list from the Data API -- full description, tags, duration, view and
     like counts. Documented, costs 1 quota unit against search's 100.
  2. The public timedtext endpoint -- the caption track, when the uploader
     published one.
  3. Nothing, and the bot stays with the title.

captions.list is not a candidate: downloading caption tracks through the API
requires OAuth as the video's owner.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
VIDEO_IDS = sys.argv[1:] or ["UO5MqethuEM", "acaAW3p5Tqw", "-3rqyw_l3gU"]

UA = "Loopback/0.1 (research feed; contact via project repository)"


def get(url, headers=None):
    request = urllib.request.Request(url)
    request.add_header("User-Agent", UA)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


print("=== 1. videos.list (documented, 1 unit) ===")
if not KEY:
    print("  no YOUTUBE_API_KEY")
else:
    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({
        "key": KEY, "id": ",".join(VIDEO_IDS),
        "part": "snippet,contentDetails,statistics",
    })
    try:
        data = json.loads(get(url).decode("utf-8"))
        for item in data.get("items", []):
            snippet = item.get("snippet") or {}
            stats = item.get("statistics") or {}
            desc = (snippet.get("description") or "").strip()
            print("  %s  %s" % (item["id"], (snippet.get("title") or "")[:52]))
            print("     channel     : %s" % snippet.get("channelTitle"))
            print("     duration    : %s" % (item.get("contentDetails") or {}).get("duration"))
            print("     views/likes : %s / %s"
                  % (stats.get("viewCount"), stats.get("likeCount")))
            print("     tags        : %s" % ", ".join((snippet.get("tags") or [])[:6]))
            print("     description : %s" % (desc[:180].replace("\n", " ") or "(empty)"))
            print()
    except urllib.error.HTTPError as exc:
        print("  HTTP %s -- %s" % (exc.code, exc.read().decode()[:200]))

print("=== 2. timedtext captions (public endpoint) ===")
for video_id in VIDEO_IDS:
    for params in (
        {"v": video_id, "lang": "en", "fmt": "json3"},
        {"v": video_id, "lang": "en"},
        {"v": video_id, "lang": "en", "kind": "asr", "fmt": "json3"},
    ):
        url = "https://www.youtube.com/api/timedtext?" + urllib.parse.urlencode(params)
        try:
            body = get(url)
        except urllib.error.HTTPError as exc:
            print("  %s %-34s HTTP %s" % (video_id, str(params)[:34], exc.code))
            continue
        except Exception as exc:  # noqa: BLE001
            print("  %s %-34s %s" % (video_id, str(params)[:34], str(exc)[:40]))
            continue
        if not body:
            print("  %s %-34s empty" % (video_id, str(params)[:34]))
            continue
        print("  %s %-34s %d bytes" % (video_id, str(params)[:34], len(body)))
        print("     %s" % body[:160])
        break
