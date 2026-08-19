"""One-shot patch for discovery.py, applied after the first live smoke run."""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "discovery.py"
s = p.read_text(encoding="utf-8")
before = s

# 1. Theora (.ogv) no longer plays in Chrome, and .mov is unreliable inline.
s = s.replace(
    'VIDEO_EXTENSIONS = (".mp4", ".webm", ".ogv", ".mov", ".m4v")',
    '# Formats that actually play inline in a current browser. Theora (.ogv) is\n'
    '# excluded: Chrome dropped support, so those results would be dead frames.\n'
    'VIDEO_EXTENSIONS = (".mp4", ".webm", ".m4v")\n'
    '\n'
    '# A feed autoplays whatever is on screen, so a 400MB master scan is not a\n'
    '# candidate no matter how relevant it is.\n'
    'MAX_BYTES = 60_000_000\n'
    'MIN_BYTES = 150_000'
)

# 2. NASA collection hrefs arrive with spaces in them; encode before use.
s = s.replace(
    'def _throttle(source):',
    'def _safe_url(url):\n'
    '    """Percent-encode a path that a catalogue handed back unencoded."""\n'
    '    parts = urllib.parse.urlsplit(str(url))\n'
    '    return urllib.parse.urlunsplit((\n'
    '        parts.scheme, parts.netloc,\n'
    '        urllib.parse.quote(parts.path, safe="/%"),\n'
    '        urllib.parse.quote(parts.query, safe="=&%"), parts.fragment,\n'
    '    ))\n'
    '\n'
    '\n'
    'def _throttle(source):',
    1,
)
s = s.replace(
    '    request = urllib.request.Request(url)\n'
    '    request.add_header("User-Agent", USER_AGENT)',
    '    request = urllib.request.Request(_safe_url(url))\n'
    '    request.add_header("User-Agent", USER_AGENT)',
)

# 3. Archive was sorting by popularity, which ignored the query entirely.
s = s.replace(
    """            "q": '%s AND mediatype:(movies)' % query,
            "rows": max(3, limit * 2),
            "page": 1,
            "output": "json",
            "sort[]": "downloads desc",""",
    """            # Search the title rather than the full text, and take the
            # default relevance ordering -- sorting by downloads returns the
            # site's most popular items regardless of the query.
            "q": 'title:(%s) AND mediatype:(movies)' % query,
            "rows": max(5, limit * 3),
            "page": 1,
            "output": "json",""",
)

# 4. Size-bound the chosen derivative.
s = s.replace(
    """        candidates.sort(key=lambda f: int(f.get("size") or 0))
        playable = next(
            (f for f in candidates if int(f.get("size") or 0) > 200_000), None
        ) or (candidates[0] if candidates else None)
        if not playable:
            continue""",
    """        candidates.sort(key=lambda f: int(f.get("size") or 0))
        playable = next(
            (f for f in candidates
             if MIN_BYTES < int(f.get("size") or 0) <= MAX_BYTES),
            None,
        )
        if not playable:
            continue""",
)

# Same ceiling for Commons.
s = s.replace(
    """        extra = info.get("extmetadata") or {}
        found.append({""",
    """        if int(info.get("size") or 0) > MAX_BYTES:
            continue
        extra = info.get("extmetadata") or {}
        found.append({""",
)

if s == before:
    print("no change -- patch already applied?")
else:
    p.write_text(s, encoding="utf-8")
    print("discovery.py patched")

for marker in ("MAX_BYTES", "_safe_url", "title:(%s)", '".mp4", ".webm", ".m4v"'):
    print("  %-22s %s" % (marker, "present" if marker in s else "MISSING"))
