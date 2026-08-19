"""Look at the raw responses from Archive and Commons to see where results die."""
import json
import pathlib
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import discovery  # noqa: E402

QUERY = sys.argv[1] if len(sys.argv) > 1 else "storm"


def archive_forms():
    forms = {
        "title only": 'title:(%s) AND mediatype:(movies)' % QUERY,
        "bare + mediatype": '%s AND mediatype:(movies)' % QUERY,
        "title or desc": '(title:(%s) OR description:(%s)) AND mediatype:(movies)'
                         % (QUERY, QUERY),
    }
    for label, q in forms.items():
        url = ("https://archive.org/advancedsearch.php?"
               + urllib.parse.urlencode({"q": q, "rows": 8, "page": 1,
                                         "output": "json"})
               + "&fl[]=identifier&fl[]=title")
        try:
            data = discovery._get_json(url, source="archive")
        except discovery.DiscoveryError as exc:
            print("  %-18s ERROR %s" % (label, exc))
            continue
        docs = (data.get("response") or {}).get("docs") or []
        print("  %-18s %d docs: %s" % (
            label, len(docs), ", ".join(d.get("title", "?")[:26] for d in docs[:3])))
        if docs:
            ident = docs[0]["identifier"]
            meta = discovery._get_json(
                "https://archive.org/metadata/%s" % urllib.parse.quote(ident),
                source="archive")
            files = meta.get("files") or []
            vids = [(f.get("name"), int(f.get("size") or 0)) for f in files
                    if str(f.get("name", "")).lower().endswith(
                        (".mp4", ".webm", ".m4v", ".ogv"))]
            print("      %r has %d video files:" % (ident, len(vids)))
            for name, size in sorted(vids, key=lambda x: x[1])[:5]:
                print("        %8.1fMB  %s" % (size / 1e6, name[:60]))


def commons_forms():
    forms = {
        "filetype:video": "filetype:video %s" % QUERY,
        "filemime webm": "filemime:video/webm %s" % QUERY,
        "plain": QUERY,
    }
    for label, search in forms.items():
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": search, "gsrnamespace": 6, "gsrlimit": 8,
            "prop": "imageinfo", "iiprop": "url|size|mime",
        })
        try:
            data = discovery._get_json(url, source="wikimedia")
        except discovery.DiscoveryError as exc:
            print("  %-18s ERROR %s" % (label, exc))
            continue
        if "error" in data:
            print("  %-18s API error: %s" % (label, json.dumps(data["error"])[:160]))
            continue
        pages = (data.get("query") or {}).get("pages") or {}
        print("  %-18s %d pages" % (label, len(pages)))
        for page in list(pages.values())[:4]:
            info = (page.get("imageinfo") or [{}])[0]
            print("      %-9s %6.1fMB  %s" % (
                info.get("mime", "?"), int(info.get("size") or 0) / 1e6,
                str(page.get("title", ""))[:56]))


print("query = %r\n" % QUERY)
print("Internet Archive")
print("-" * 60)
archive_forms()
print("\nWikimedia Commons")
print("-" * 60)
commons_forms()
