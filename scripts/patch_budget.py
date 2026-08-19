"""Keep discovery inside the free tiers it depends on.

Pexels allows 200 requests an hour and 20,000 a month. Five bots foraging at
0.45-0.70 per 60-second tick is roughly 180 searches an hour, which sits on
that ceiling and blows the monthly allowance in under a week.

Two changes keep it comfortable without slowing the feed:

  * A much longer cache. A subject's search results do not change minute to
    minute, and each cached result set yields several distinct clips because
    pick() excludes URLs already posted.
  * A per-source hourly call budget. When it is spent, the source stops being
    called and whatever is cached is used instead. The feed keeps moving; the
    key does not get throttled.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "discovery.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    """TIMEOUT = 20
CACHE_TTL = 1800          # half an hour; these catalogues do not move fast
MIN_SECONDS_BETWEEN = 3.0  # per source""",
    """TIMEOUT = 20
# Six hours. A subject's results barely move, and one cached set yields several
# distinct clips because pick() skips URLs already posted.
CACHE_TTL = 21600
MIN_SECONDS_BETWEEN = 3.0  # per source

# Hourly call ceilings, set below each provider's free tier so a busy day never
# reaches the point where the key is throttled. Once spent, a source falls back
# to whatever is already cached.
HOURLY_BUDGET = {"pexels": 120, "pixabay": 120, "nasa": 200, "wikimedia": 60}
_budget_lock = threading.Lock()
_calls = {}  # source -> [window_start_monotonic, count]


def budget_remaining(source):
    ceiling = HOURLY_BUDGET.get(source)
    if ceiling is None:
        return 1
    now = time.monotonic()
    with _budget_lock:
        window = _calls.get(source)
        if not window or now - window[0] >= 3600:
            _calls[source] = [now, 0]
            return ceiling
        return max(0, ceiling - window[1])


def _spend(source):
    \"\"\"Claim one call against the hourly ceiling. False if it is spent.\"\"\"
    ceiling = HOURLY_BUDGET.get(source)
    if ceiling is None:
        return True
    now = time.monotonic()
    with _budget_lock:
        window = _calls.get(source)
        if not window or now - window[0] >= 3600:
            _calls[source] = [now, 1]
            return True
        if window[1] >= ceiling:
            return False
        window[1] += 1
        return True""",
)

# Enforce the ceiling at the point every source goes out to the network.
s = s.replace(
    '''def _throttle(source):
    """Never hit one source faster than MIN_SECONDS_BETWEEN."""''',
    '''def _throttle(source):
    """Never hit one source faster than MIN_SECONDS_BETWEEN."""
    if not _spend(source):
        raise DiscoveryError("%s hourly budget spent" % source)''',
)

# Report it, so the ceiling is visible rather than a silent behaviour change.
s = s.replace(
    '''def cache_stats():
    with _cache_lock:
        return {"entries": len(_cache), "sources": sorted(SOURCES)}''',
    '''def cache_stats():
    with _cache_lock:
        entries = len(_cache)
    return {
        "entries": entries,
        "sources": sorted(SOURCES),
        "hourly_remaining": {
            source: budget_remaining(source) for source in HOURLY_BUDGET
        },
    }''',
)

p.write_text(s, encoding="utf-8")
print("discovery.py patched")
for marker in ("HOURLY_BUDGET", "_spend(", "CACHE_TTL = 21600", "hourly_remaining"):
    print("  %-20s %s" % (marker, "present" if marker in s else "MISSING"))
