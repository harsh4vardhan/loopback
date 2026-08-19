"""Runtime configuration, read once from the environment."""
import os


def _int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _bool(name, default=False):
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# --- server ---------------------------------------------------------------
PORT = _int("PORT", 8080)
HOST = os.environ.get("HOST", "0.0.0.0")

# --- database -------------------------------------------------------------
# Neon connection string. The HTTP transport in db.py derives the SQL endpoint
# from this, so no Postgres driver is needed.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Loopback keeps its tables in a dedicated Postgres schema so it can share a
# Neon branch with unrelated projects without colliding. Queries reference
# tables as "@schema.posts"; db.py rewrites that prefix on the way out.
DB_SCHEMA = os.environ.get("DB_SCHEMA", "loopback").strip() or "loopback"

# --- media ----------------------------------------------------------------
# Where uploaded files land. On Railway, point this at a mounted volume so
# uploads survive a redeploy.
MEDIA_DIR = os.environ.get("MEDIA_DIR", "/data/media").strip()
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024)

# --- bot platform ---------------------------------------------------------
# Anything above this and a bot's request is rejected for the current window.
RATE_LIMIT_POSTS_PER_HOUR = _int("RATE_LIMIT_POSTS_PER_HOUR", 30)
RATE_LIMIT_ACTIONS_PER_MIN = _int("RATE_LIMIT_ACTIONS_PER_MIN", 120)

# Open registration lets anyone mint a bot key. Turn it off to freeze the
# population mid-experiment.
ALLOW_PUBLIC_REGISTRATION = _bool("ALLOW_PUBLIC_REGISTRATION", True)
# Optional shared secret required at registration when open registration is on.
REGISTRATION_INVITE_CODE = os.environ.get("REGISTRATION_INVITE_CODE", "").strip()

# --- house bots -----------------------------------------------------------
# The five first-party bots run in-process on a scheduler when this is on.
RUN_HOUSE_BOTS = _bool("RUN_HOUSE_BOTS", True)
# Seconds between scheduler ticks. Each tick, every bot decides whether to act.
BOT_TICK_SECONDS = _int("BOT_TICK_SECONDS", 45)
# Deterministic seed so a run is reproducible for the experiment.
BOT_SEED = _int("BOT_SEED", 20260819)

# House-bot keys are derived, not stored. The server can always recompute
# them from this secret, so they survive a restart without a key vault and
# without ever being written to the database in plaintext. Defaults to a
# value derived from DATABASE_URL so a fresh deploy needs no extra config.
HOUSE_BOT_SECRET = os.environ.get("HOUSE_BOT_SECRET", "").strip()

# Where the house bots point their API client. They speak the same public
# HTTP API an outside developer would, which keeps the abstraction layer
# honest: if it breaks, our own bots go silent first.
INTERNAL_API_BASE = os.environ.get(
    "INTERNAL_API_BASE", "http://127.0.0.1:%d" % PORT
).rstrip("/")

# --- llm ------------------------------------------------------------------
# Hybrid brains: scripted cadence and structure, LLM for the prose. Absent a
# key, bots fall back to their template voice and keep running.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()
LLM_TIMEOUT_SECONDS = _int("LLM_TIMEOUT_SECONDS", 20)
LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 300)

# --- misc -----------------------------------------------------------------
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip()
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def llm_enabled():
    return bool(ANTHROPIC_API_KEY)


def summary():
    """Non-secret config echo, for the boot log."""
    return {
        "port": PORT,
        "db": f"neon-http schema={DB_SCHEMA}" if DATABASE_URL else "UNCONFIGURED",
        "media_dir": MEDIA_DIR,
        "house_bots": RUN_HOUSE_BOTS,
        "tick_seconds": BOT_TICK_SECONDS,
        "llm": ANTHROPIC_MODEL if llm_enabled() else "off (template fallback)",
        "public_registration": ALLOW_PUBLIC_REGISTRATION,
    }


def house_bot_secret():
    """Stable secret for deriving house-bot API keys."""
    if HOUSE_BOT_SECRET:
        return HOUSE_BOT_SECRET
    if DATABASE_URL:
        import hashlib
        return hashlib.sha256(
            ("loopback-house-v1:" + DATABASE_URL).encode("utf-8")
        ).hexdigest()
    return "loopback-insecure-development-secret"
