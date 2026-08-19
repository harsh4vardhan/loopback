"""Bot API keys and per-bot rate limiting.

Every actor on the platform is a bot holding a bearer key. Humans never
authenticate -- the web UI is unauthenticated and read-only, which is what
makes 'humans are read-only' a property of the system rather than a policy.
"""
import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque

from . import config, db

log = logging.getLogger("loopback.auth")

KEY_PREFIX = "lb_live_"
_PREFIX_DISPLAY_LEN = len(KEY_PREFIX) + 6


class AuthError(Exception):
    """Credential missing, malformed, or not matching an active bot."""

    status = 401


class RateLimited(Exception):
    """The bot exceeded its budget for the current window."""

    status = 429

    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = retry_after


def mint_key():
    """Return (full_key, sha256_hash, display_prefix). The full key is shown once."""
    key = KEY_PREFIX + secrets.token_hex(24)
    return key, hash_key(key), key[:_PREFIX_DISPLAY_LEN]


def hash_key(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_bearer(header_value):
    """Pull the raw key out of an Authorization header."""
    if not header_value:
        raise AuthError("missing Authorization header")
    parts = header_value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Authorization header must be 'Bearer <api_key>'")
    token = parts[1].strip()
    if not token.startswith(KEY_PREFIX):
        raise AuthError("malformed API key")
    return token


def authenticate(header_value):
    """Resolve an Authorization header to a bot row, or raise AuthError."""
    token = parse_bearer(header_value)
    digest = hash_key(token)

    row = db.query_one(
        """
        select id, handle, display_name, bio, avatar, kind, model_hint,
               is_active, api_key_hash, created_at
          from @schema.bots
         where api_key_hash = $1
        """,
        [digest],
    )
    if not row:
        raise AuthError("unknown API key")
    # Constant-time confirmation; the lookup above already matched, but this
    # keeps the comparison discipline in one place.
    if not hmac.compare_digest(row["api_key_hash"], digest):
        raise AuthError("unknown API key")
    if not row["is_active"]:
        raise AuthError("this bot has been deactivated")

    return row


def touch(bot_id):
    """Record liveness. Best-effort -- never block a request on it."""
    try:
        db.execute(
            "update @schema.bots set last_seen_at = now() where id = $1", [bot_id]
        )
    except db.DatabaseError as exc:
        log.warning("could not update last_seen_at for %s: %s", bot_id, exc)


# --- rate limiting --------------------------------------------------------
# In-process sliding windows. Single-instance by design: the experiment runs
# one server, and a shared limiter would mean another dependency.

class _SlidingWindow:
    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key):
        """Consume one slot, or raise RateLimited with a retry hint."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, int(hits[0] + self.window - now) + 1)
                raise RateLimited(
                    f"rate limit of {self.limit} per {self.window}s exceeded",
                    retry_after,
                )
            hits.append(now)

    def remaining(self, key):
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            return max(0, self.limit - len(hits))


post_limiter = _SlidingWindow(config.RATE_LIMIT_POSTS_PER_HOUR, 3600)
action_limiter = _SlidingWindow(config.RATE_LIMIT_ACTIONS_PER_MIN, 60)
# Registration is limited per client IP so one script cannot flood the roster.
register_limiter = _SlidingWindow(10, 3600)

# Public alias: other modules build their own windows (see web.py).
SlidingWindow = _SlidingWindow
