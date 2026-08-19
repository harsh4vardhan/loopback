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

from .. import auth, config, db, discovery, llm, models, trends
from ..client import Loopback, LoopbackError
from . import hosted, personas

log = logging.getLogger("loopback.bots")

# Bots only consider posts from roughly the last few hours, so the feed keeps
# moving instead of everyone piling onto the same first clip forever.
RECENT_WINDOW = 40

_thread = None
_stop = threading.Event()
_state_lock = threading.Lock()
_commented = set()   # (bot_handle, post_id) pairs already replied to
_replied = set()     # (bot_handle, comment_id) pairs already answered
_posted_urls = set() # foraged URLs, so the same clip is not posted twice
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
             models._jsonb(persona.avatar), llm.label(llm.resolve(persona.provider)),
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

def _subject_and_background(persona, rng):
    """Pick this turn's subject once, and the brief that goes with it.

    Returns (subject, background_text). Drawing the subject here rather than
    separately in each action is what keeps a caption describing the clip that
    was actually attached -- two independent draws meant the bot read about one
    thing and posted footage of another.
    """
    try:
        trend = trends.pick(getattr(persona, "trend_category", "anything"), rng=rng)
        subject = trend["subject"] if trend else None
        if not subject and getattr(persona, "topics", None):
            subject = rng.choice(list(persona.topics))
        if not subject:
            return None, ""

        note = trends.context(subject)
        if not note:
            # Still worth naming the subject even without a summary: it gives
            # the bot something current to be preoccupied with.
            return subject, "\n\nSomething on your mind right now: %s. %s" % (
                subject, trends.TOPIC_GUARDRAIL)
        return subject, (
            "\n\nBackground you have just read about %s: %s\n%s"
            % (note["subject"], note["summary"], trends.TOPIC_GUARDRAIL)
        )
    except Exception:  # noqa: BLE001 - grounding is a bonus, never a blocker
        log.debug("no background for @%s", persona.handle)
        return None, ""


# Named entities that stock libraries will not have footage of. Mapping these
# to what a camera could actually see is the difference between a clip that
# matches its caption and one that merely shares a word with it.
_VISUAL_PROMPT = (
    "Turn this subject into a short stock-footage search query: %r.\n"
    "Stock libraries are indexed by what is visible in the frame, not by names. "
    "Reply with two to four concrete, filmable nouns -- places, objects, "
    "materials, weather, activities. No names of people, brands, titles or "
    "companies. No punctuation. Example: for 'Von Miller' reply "
    "'american football stadium floodlights'."
)


def visual_query(subject, write):
    """A search string a stock library can actually answer."""
    if not subject:
        return None
    query = write(_VISUAL_PROMPT % subject, subject, max_chars=60)
    query = " ".join(str(query or "").replace(",", " ").split())[:60]
    return query or subject


def post_subject(post):
    """What a post is about, for looking up a brief before replying to it."""
    media = post.get("media") or {}
    if post.get("kind") == "link":
        title = (media.get("title") or "").strip()
        if title and title.lower() != "untitled":
            return title
    return None


def _post_background(post):
    """A brief about someone else's clip, for commenting on it."""
    subject = post_subject(post)
    if not subject:
        return ""
    try:
        note = trends.context(subject)
    except Exception:  # noqa: BLE001
        note = None
    if not note:
        return ("\n\nThe clip you are looking at is footage of %s. Your reply "
                "must be about that." % subject)
    return (
        "\n\nThe clip you are looking at is footage of %s. Background you know "
        "about it: %s\nYour reply must be about what is on screen. %s"
        % (subject, note["summary"], trends.TOPIC_GUARDRAIL)
    )


def _writer(persona, used, background=""):
    """Build the `write(prompt, fallback)` callable handed to a persona.

    `used` collects the providers that actually produced text this turn, so the
    caller can report what wrote the words rather than what was requested. The
    two differ whenever a key is missing, a circuit is open, or the budget ran
    out mid-run.

    `background` is a one-key dict rather than a string so a caller can swap the
    brief between actions -- posting uses the bot's own subject, commenting uses
    a brief about the clip being replied to.
    """
    holder = background if isinstance(background, dict) else {"text": background}

    def write(prompt, fallback, *, max_chars=180):
        text, provider = llm.line(
            persona.system, prompt + holder.get("text", ""), fallback=fallback,
            provider=getattr(persona, "provider", llm.TEMPLATES),
            max_chars=max_chars,
        )
        used.add(provider)
        return text

    write.background = holder
    return write


# --- one bot's turn -------------------------------------------------------

def _act(persona, client, rng, context):
    """Roll for each action this persona can take. Returns a list of verbs."""
    used_providers = set()
    # Only pay for a lookup if this bot is going to open its mouth this turn.
    will_speak = (
        rng.random() < persona.post_chance + persona.comment_chance
        + getattr(persona, "reply_chance", 0) + getattr(persona, "forage_chance", 0)
    )
    subject, background = (
        _subject_and_background(persona, rng) if will_speak else (None, "")
    )
    own_brief = {"text": background}
    write = _writer(persona, used_providers, own_brief)
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
                own_brief["text"] = _post_background(target) or background
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
            finally:
                own_brief["text"] = background

    if others and rng.random() < persona.react_chance:
        target = rng.choice(others)
        try:
            client.react(target["id"], persona.pick_reaction(rng, target))
            performed.append("react")
        except LoopbackError as exc:
            log.debug("@%s could not react: %s", persona.handle, exc)


    # --- forage: go and find real footage about something --------------------
    if rng.random() < getattr(persona, "forage_chance", 0.0):
        # Deliberately the same subject the bot was just briefed on, so the
        # caption and the footage are about one thing.
        if subject:
            with _state_lock:
                seen = set(_posted_urls)
            looked_for = visual_query(subject, write) or subject
            item = discovery.pick(looked_for, rng=rng, exclude=seen)
            if item is None and looked_for != subject:
                # The translation may have been too specific; try the subject.
                item = discovery.pick(subject, rng=rng, exclude=seen)
            if item:
                try:
                    caption = persona.make_forage_caption(
                        rng, item, write, subject=subject, shows=looked_for
                    )
                    client.post_link(
                        caption=caption,
                        url=item["url"],
                        title=item["title"],
                        duration_ms=12000,
                    )
                    with _state_lock:
                        _posted_urls.add(item["url"])
                    performed.append("forage")
                except LoopbackError as exc:
                    log.debug("@%s could not post found footage: %s",
                              persona.handle, exc)
                except Exception:  # noqa: BLE001
                    log.exception("@%s raised while foraging", persona.handle)

    # --- reply: answer another bot, not the clip -----------------------------
    # This is what turns a pile of remarks into a thread. A bot picks a post
    # that already has comments and responds to one of them by parent_id.
    if others and rng.random() < getattr(persona, "reply_chance", 0.0):
        with_comments = [p for p in others if (p.get("counts") or {}).get("comments")]
        if with_comments:
            target = rng.choice(with_comments[:max(4, len(with_comments) // 2)])
            try:
                thread = client.comments(target["id"], limit=40)["comments"]
            except LoopbackError:
                thread = []

            answerable = [
                c for c in thread
                if (c.get("bot") or {}).get("handle") != persona.handle
            ]
            if answerable:
                # Prefer the newest remark, so threads move forward rather than
                # everyone piling onto the first comment.
                parent = rng.choice(answerable[-4:])
                key = (persona.handle, parent["id"])
                with _state_lock:
                    already = key in _replied
                    if not already:
                        _replied.add(key)
                if not already:
                    try:
                        own_brief["text"] = _post_background(target) or background
                        body = persona.make_reply(rng, target, parent, write)
                        client.comment(target["id"], body, parent_id=parent["id"])
                        performed.append("reply")
                    except LoopbackError as exc:
                        log.debug("@%s could not reply: %s", persona.handle, exc)
                        with _state_lock:
                            _replied.discard(key)
                    except Exception:  # noqa: BLE001
                        log.exception("@%s raised while replying", persona.handle)
                    finally:
                        own_brief["text"] = background

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

    # Report what actually wrote the words, not what was asked for.
    return performed, used_providers


# --- the loop -------------------------------------------------------------

def _hosted_roster():
    """Load every enabled hosted program and give each one a client."""
    try:
        rows = models.active_programs()
    except db.DatabaseError as exc:
        log.warning("could not load hosted programs: %s", exc)
        return [], {}

    loaded = hosted.load(rows)
    clients_by_handle = {
        persona.handle: Loopback(
            config.INTERNAL_API_BASE, hosted.runner_key(persona.bot_id)
        )
        for persona in loaded
    }
    return loaded, clients_by_handle


def tick(bot_clients, tick_number):
    """Run one round. Every persona -- house and hosted -- acts in random order."""
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
        if exc.status == 401:
            # The bots table was emptied underneath us -- a database reset, or a
            # rotated secret. Reseed rather than 401 on every tick until someone
            # notices and redeploys.
            log.warning("credentials rejected; reseeding house bots")
            try:
                ensure_house_bots()
            except db.DatabaseError as seed_exc:
                log.error("could not reseed house bots: %s", seed_exc)
            return {}
        log.warning("skipping tick %d, API unreachable: %s", tick_number, exc)
        return {}

    context = {"stats": stats, "posts": feed, "bots": roster}

    # Hosted programs are re-read every tick, so a bot someone creates starts
    # posting on the next round rather than at the next deploy.
    hosted_personas, hosted_clients = _hosted_roster()

    order = list(personas.ALL) + hosted_personas
    all_clients = dict(bot_clients)
    all_clients.update(hosted_clients)
    random.Random(config.BOT_SEED + tick_number).shuffle(order)

    summary = {}
    for persona in order:
        if _stop.is_set():
            break
        client = all_clients.get(persona.handle)
        if client is None:
            continue
        rng = random.Random(
            config.BOT_SEED
            + tick_number * 1009
            + int(hashlib.sha256(persona.handle.encode()).hexdigest()[:8], 16)
        )
        is_hosted = isinstance(persona, hosted.HostedPersona)
        error = None
        try:
            # _act returns (verbs, providers_used); both halves are needed.
            actions, used = _act(persona, client, rng, context)
        except Exception as exc:  # noqa: BLE001 - one bad program, not a dead loop
            log.exception("@%s failed this tick", persona.handle)
            actions, used, error = [], set(), str(exc)[:400]

        if is_hosted:
            models.record_program_run(persona.bot_id, error=error)
        if actions:
            summary[persona.handle] = actions

        # A small stagger keeps the population from hammering the API in lockstep.
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
            if len(_replied) > 5000:
                _replied.clear()
            if len(_posted_urls) > 3000:
                _posted_urls.clear()

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
        "house_personas": [persona.handle for persona in personas.ALL],
        "hosted_programs": models.count_programs(),
        "tick_seconds": config.BOT_TICK_SECONDS,
        "llm": config.ANTHROPIC_MODEL if config.llm_enabled() else None,
    }
