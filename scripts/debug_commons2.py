"""Narrow down which Commons search syntax actually surfaces video."""
import pathlib
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import discovery  # noqa: E402

VARIANTS = [
    ("filetype alone", "filetype:video"),
    ("filetype+term", "filetype:video storm"),
    ("filemime webm", "filemime:video/webm"),
    ("filemime webm+term", "storm filemime:video/webm"),
    ("filemime mp4", "filemime:video/mp4"),
    ("filemime ogg", "filemime:application/ogg"),
    ("filetype video term2", "aurora filetype:video"),
]

for label, search in VARIANTS:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": search, "gsrnamespace": 6, "gsrlimit": 5,
        "prop": "imageinfo", "iiprop": "url|size|mime",
    })
    try:
        data = discovery._get_json(url, source="wikimedia")
    except discovery.DiscoveryError as exc:
        print("%-22s ERROR %s" % (label, exc))
        continue
    if "error" in data:
        print("%-22s API error: %s" % (label, str(data["error"])[:120]))
        continue
    pages = (data.get("query") or {}).get("pages") or {}
    mimes = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mimes.append("%s %s" % (
            info.get("mime", "?"), str(page.get("title", "")).replace("File:", "")[:34]))
    print("%-22s %d results" % (label, len(pages)))
    for m in mimes[:3]:
        print("      %s" % m)
        print("        %s" % next(
            ((p.get("imageinfo") or [{}])[0].get("url", "") or "")[:100]
            for p in pages.values()
            if str(p.get("title", "")).replace("File:", "")[:34] in m
        ))
