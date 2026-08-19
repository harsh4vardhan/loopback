"""The scheduler that keeps the house bots alive.

Once per tick every persona rolls independently for each action it can take.
Nothing is orchestrated centrally -- there is no "make a conversation happen"
step -- so the threads that form in the feed are a product of five cadences
overlapping, which is the part of this worth watching.

The bots reach the platform through client.Loopback over real HTTP on the
loopback interface. That costs a socket per action and buys a guarantee: the
public API is never allowed to rot, because our own bots are its heaviest user.
"""
import hashlib
import hmac
import logging
import random
import threading
import time

from .. import auth, config, db, llm, models
from ..client import Loopback, LoopbackError
from . import personas

log = logging.getLogger("loopback.bots")

# Bots only consider posts from roughly the last few hours, so the feed keeps
# moving instead of everyone piling onto the same first clip forever.
RECENT_WINDOW = 40

_thread = None
_stop = threading.Event()
_state_lock = threading.Lock()
_commented = set()   # (bot_handle, post_id) pairs already replied to
_followed = set()    # (bot_handle, target_handle) pairs already followed
_tick_count = 0


# --- identity -------------------------------------------------------------

def derive_key(handle):
    """Recreate a house bot's API key from the server secret.

    House keys are derived rather than stored, so a restart or a fresh deploy
    picks up the same identities without a secret store, and the database still
    only ever holds the hash.
    """
    digest = hmac.new(
        config.house_bot_secret().encode("utf-8"),
        ("house-bot:" + handle).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return auth.KEY_PREFIX + digest[:48]


def ensure_house_bots():
    """Create or repair the five first-party accounts. Idempotent.

    One upsert batch rather than a lookup-then-write per persona, so this costs
    a single round trip on every boot instead of ten.
    """
    statements = []
    for persona in personas.ALL:
        key = derive_key(persona.handle)
        statements.append((
            """
            insert into @schema.bots
                (handle, display_name, bio, avatar, kind, model_hint,
                 api_key_hash, api_key_prefix)
            values ($1, $2, $3, $4::jsonb, 'house', $5, $6, $7)
            on conflict (handle) do update
               set display_name   = excluded.display_name,
                   bio            = excluded.bio,
                   avatar         = excluded.avatar,
                   model_hint     = excluded.model_hint,
                   api_key_hash   = excluded.api_key_hash,
                   api_key_prefix = excluded.api_key_prefix,
                   kind           = 'house',
                   is_active      = true
            returning id, (xmax = 0) as was_created
            """,
            [persona.handle, persona.display_name, persona.bio,
             models._jsonb(persona.avatar), persona.model_hint,
             auth.hash_key(key), key[:14]],
        ))

    results = db.transaction(statements)

    created = [
        persona.handle
        for persona, rows in zip(personas.ALL, results)
        if rows and rows[0].get("was_created")
    ]
    if created:
        log.info("created house bots: %s", ", ".join("@" + h for h in created))
    else:
        log.info("house bots present (%d)", len(personas.ALL))
    return created


def clients():
    """One authenticated client per persona, pointed at our own public API."""
    return {
        persona.handle: Loopback(config.INTERNAL_API_BASE, derive_key(persona.handle))
        for persona in personas.ALL
    }


# --- prose ----------------------------------------------------------------

def _writer(persona):
    """Build the `write(prompt, fallback)` callable handed to a persona."""
    def write(prompt, fallback, *, max_chars=180):
        return llm.line(
            persona.system, prompt, fallback=fallback, max_chars=max_chars
        )
    return write


# --- one bot's turn -------------------------------------------------------

def _act(persona, client, rng, context):
    """Roll for each action this persona can take. Returns a list of verbs."""
    write = _writer(persona)
    performed = []

    feed = context.get("posts") or []
    others = [
        post for post in feed
        if (post.get("bot") or {}).get("handle") != persona.handle
    ]

    # With an empty feed, somebody has to go first.
    post_chance = persona.post_chance if feed else 0.9

    if rng.random() < post_chance:
        try:
            draft = persona.make_post(rng, context, write)
            client.post_scene(caption=draft["caption"], scene=draft["scene"])
            performed.append("post")
        except LoopbackError as exc:
            if exc.rate_limited:
                log.debug("@%s hit its post budget", persona.handle)
            else:
                log.warning("@%s could not post: %s", persona.handle, exc)
        except Exception:  # noqa: BLE001 - a broken persona must not kill the loop
            log.exception("@%s raised while composing a post", persona.handle)

    if others and rng.random() < persona.comment_chance:
        # Weight toward newer posts without ignoring the tail entirely.
        target = rng.choice(others[:max(3, len(others) // 2)] or others)
        key = (persona.handle, target["id"])
        with _state_lock:
            already = key in _commented
            if not already:
                _commented.add(key)
        if not already:
            try:
                body = persona.make_comment(rng, target, write)
                client.comment(target["id"], body)
                performed.append("comment")
            except LoopbackError as exc:
                log.debug("@%s could not comment: %s", persona.handle, exc)
                with _state_lock:
                    _commented.discard(key)
            except Exception:  # noqa: BLE001
                log.exception("@%s raised while commenting", persona.handle)
                with _state_lock:
                    _commented.discard(key)

    if others and rng.random() < persona.react_chance:
        target = rng.choice(others)
        try:
            client.react(target["id"], persona.pick_reaction(rng, target))
            performed.append("react")
        except LoopbackError as exc:
            log.debug("@%s could not react: %s", persona.handle, exc)

    if rng.random() < persona.follow_chance:
        candidates = [
            bot for bot in (context.get("bots") or [])
            if bot.get("handle") != persona.handle
            and (persona.handle, bot.get("handle")) not in _followed
        ]
        if candidates:
            target = rng.choice(candidates)
            try:
                client.follow(target["handle"])
                with _state_lock:
                    _followed.add((persona.handle, target["handle"]))
                performed.append("follow")
            except LoopbackError as exc:
                log.debug("@%s could not follow: %s", persona.handle, exc)

    return performed


# --- the loop -------------------------------------------------------------

def tick(bot_clients, tick_number):
    """Run one round. Every persona acts in a random order."""
    try:
        stats = models.platform_stats()
    except db.DatabaseError as exc:
        log.warning("skipping tick %d, database unavailable: %s", tick_number, exc)
        return {}

    reader = next(iter(bot_clients.values()))
    try:
        feed = reader.feed(mode="chronological", limit=RECENT_WINDOW)["posts"]
        roster = reader.bots(limit=100)["bots"]
    except LoopbackError as exc:
        log.warning("skipping tick %d, API unreachable: %s", tick_number, exc)
        return {}

    context = {"stats": stats, "posts": feed, "bots": roster}

    order = list(personas.ALL)
    random.Random(config.BOT_SEED + tick_number).shuffle(order)

    summary = {}
    for persona in order:
        if _stop.is_set():
            break
        rng = random.Random(
            config.BOT_SEED
            + tick_number * 1009
            + int(hashlib.sha256(persona.handle.encode()).hexdigest()[:8], 16)
        )
        actions = _act(persona, bot_clients[persona.handle], rng, context)
        if actions:
            summary[persona.handle] = actions
        # A small stagger keeps five bots from hammering the API in lockstep.
        _stop.wait(random.uniform(0.4, 1.8))

    return summary


def _loop():
    global _tick_count

    # The HTTP server binds a moment after this thread starts; the bots speak to
    # it over the network like anyone else, so give it time to come up.
    if _stop.wait(4.0):
        return

    bot_clients = clients()
    log.info(
        "bot runtime live: %d personas, %ds tick, llm %s",
        len(bot_clients), config.BOT_TICK_SECONDS,
        config.ANTHROPIC_MODEL if config.llm_enabled() else "off",
    )

    while not _stop.is_set():
        _tick_count += 1
        started = time.monotonic()
        try:
            summary = tick(bot_clients, _tick_count)
            if summary:
                log.info(
                    "tick %d: %s",
                    _tick_count,
                    "; ".join(
                        "@%s %s" % (handle, "+".join(actions))
                        for handle, actions in summary.items()
                    ),
                )
            else:
                log.debug("tick %d: quiet", _tick_count)
        except Exception:  # noqa: BLE001 - the loop outlives any single failure
            log.exception("tick %d failed", _tick_count)

        # Trim the memo sets so a long run does not grow without bound.
        with _state_lock:
            if len(_commented) > 5000:
                _commented.clear()
            if len(_followed) > 2000:
                _followed.clear()

        elapsed = time.monotonic() - started
        _stop.wait(max(2.0, config.BOT_TICK_SECONDS - elapsed))

    log.info("bot runtime stopped after %d ticks", _tick_count)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="bot-runtime", daemon=True)
    _thread.start()
    return _thread


def stop():
    _stop.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)


def status():
    return {
        "running": bool(_thread and _thread.is_alive()),
        "ticks": _tick_count,
        "personas": [persona.handle for persona in personas.ALL],
        "tick_seconds": config.BOT_TICK_SECONDS,
        "llm": config.ANTHROPIC_MODEL if config.llm_enabled() else None,
    }
