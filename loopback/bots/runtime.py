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

from .. import auth, config, creator, db, discovery, llm, models, trends
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

# The summary behind the subject a bot is currently posting about, so it can be
# attached to the post and read by whoever replies.
_blurbs = {}


def _remember_blurb(subject, blurb, source):
    with _state_lock:
        if len(_blurbs) > 400:
            _blurbs.clear()
        _blurbs[subject] = {"blurb": blurb, "source": source}


def _blurb_for(subject):
    with _state_lock:
        return dict(_blurbs.get(subject) or {})


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

        # A wire item carries its own summary. Prefer it: Wikipedia has no
        # article called "Disabled people in England to get 24-hour support",
        # so for exactly the subjects worth reacting to the lookup returns
        # nothing and the bot is left with only the headline's wording.
        blurb = (trend or {}).get("blurb") or ""
        source = (trend or {}).get("source") or ""
        if blurb:
            _remember_blurb(subject, blurb, source)
            return subject, (
                "\n\nYou have just read this, from %s:\n%s\n%s\n%s"
                % (source or "a news feed", subject, blurb,
                   trends.TOPIC_GUARDRAIL)
            )

        note = trends.context(subject)
        if not note:
            return subject, (
                "\n\nYou have just read a headline from %s: %s\n%s"
                % (source or "a news feed", subject, trends.TOPIC_GUARDRAIL)
            )
        _remember_blurb(subject, note["summary"], "Wikipedia")
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
    "You need footage to illustrate this subject: %r.\n"
    "Stock libraries are indexed by what is visible in the frame, not by names, "
    "so reply with two to four concrete filmable nouns that would make a fitting "
    "backdrop for it -- the setting it happens in, the objects around it, the "
    "weather or light of it. Choose something evocative rather than the most "
    "literal object in the sentence. No names of people, brands, titles or "
    "companies. No punctuation.\n"
    "Examples: 'Von Miller' -> 'american football stadium floodlights'; "
    "'energy bills drive inflation to a four-month high' -> "
    "'kitchen radiator winter window condensation'."
)


def visual_query(subject, write):
    """A search string a stock library can actually answer."""
    if not subject:
        return None
    query = write(_VISUAL_PROMPT % subject, subject, max_chars=60)
    query = " ".join(str(query or "").replace(",", " ").split())[:60]
    return query or subject


def post_subject(post):
    """What a post is about, for looking up a brief before replying to it.

    The recorded subject is authoritative; the stock library's filename is a
    last resort, because it is often generic or absent.
    """
    context = post.get("context") or {}
    subject = (context.get("subject") or "").strip()
    if subject:
        return subject
    searched = (context.get("searched_for") or "").strip()
    if searched:
        return searched

    media = post.get("media") or {}
    if post.get("kind") == "link":
        title = (media.get("title") or "").strip()
        if title and title.lower() != "untitled":
            return title
    return None


def _post_background(post):
    """A brief about the post being replied to.

    The summary recorded on the post is used first. Looking the subject up
    again is pointless for anything from a wire -- there is no Wikipedia
    article named after a headline -- and falling back to the footage is what
    produced replies about fonts under stories about housing.
    """
    subject = post_subject(post)
    if not subject:
        return ""

    context = post.get("context") or {}
    blurb = (context.get("blurb") or "").strip()
    source = (context.get("trend_source") or context.get("source") or "").strip()

    if not blurb:
        remembered = _blurb_for(subject)
        blurb = remembered.get("blurb", "")
        source = source or remembered.get("source", "")

    if not blurb:
        try:
            note = trends.context(subject)
        except Exception:  # noqa: BLE001
            note = None
        if note:
            blurb = note["summary"]
            source = source or "Wikipedia"

    if not blurb:
        return (
            "\n\nThe post you are replying to is about: %s\nYour reply must be "
            "about that subject, not about what the footage looks like. %s"
            % (subject, trends.TOPIC_GUARDRAIL)
        )
    return (
        "\n\nThe post you are replying to is about: %s\nWhat you know about it"
        "%s: %s\nReply about the subject -- react to it, push back on it, or ask "
        "something real about it. Do not just describe the footage. %s"
        % (subject, (" (from %s)" % source) if source else "", blurb,
           trends.TOPIC_GUARDRAIL)
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




def _performance_by_handle(handle):
    """Look a bot up by handle and read its numbers."""
    bot = models.get_bot_by_handle(handle)
    if not bot:
        return {"_bot_id": None, "followers": 0, "views": 0, "best_post": None}
    stats = models.bot_performance(bot["id"])
    stats["_bot_id"] = bot["id"]
    return stats


def _grow(persona, client, rng, context, write, move, detail, performance):
    """Carry out one growth move. Returns True if something was published."""
    bot_id = performance.get("_bot_id")

    if move == "milestone":
        draft = persona.make_milestone_post(rng, detail, write)
        client.post_scene(caption=draft["caption"], scene=draft["scene"])
        if bot_id:
            models.record_event(
                bot_id, "milestone.posted", "bot", bot_id,
                {"kind": detail["kind"], "value": detail["value"]},
            )
        log.info("@%s marked %s %s", persona.handle, detail["value"], detail["kind"])
        return True

    if move == "followup":
        best = detail["post"]
        subject = rng.choice(list(getattr(persona, "topics", ("more of this",))))
        looked_for = visual_query(subject, write) or subject
        with _state_lock:
            seen = set(_posted_urls)
        item = discovery.pick(looked_for, rng=rng, exclude=seen)
        if not item:
            return False
        caption = persona.make_followup_caption(
            rng, best, detail["engagement"], write
        )
        client.post_link(
            caption=caption, url=item["url"], title=item["title"],
            duration_ms=12000,
        )
        with _state_lock:
            _posted_urls.add(item["url"])
        return True

    if move == "reach":
        # Comment where the attention already is, rather than on a random clip.
        popular = models.top_posts(hours=6, limit=5, exclude_bot_id=bot_id)
        for row in popular:
            post = models.post_public(row)
            key = (persona.handle, post["id"])
            with _state_lock:
                if key in _commented:
                    continue
                _commented.add(key)
            body = write(
                creator.reach_comment_prompt(post, persona._post_summary(post)),
                persona.make_comment(rng, post, write),
                max_chars=140,
            )
            client.comment(post["id"], body)
            return True
        return False

    if move == "followback":
        if not bot_id:
            return False
        pending = models.followers_not_followed_back(bot_id, limit=3)
        for follower in pending:
            client.follow(follower["handle"])
            with _state_lock:
                _followed.add((persona.handle, follower["handle"]))
            return True
        return False

    if move == "collab":
        others = [
            p for p in (context.get("posts") or [])
            if (p.get("bot") or {}).get("handle") != persona.handle
        ]
        if not others:
            return False
        target = rng.choice(others[:8])
        handle = (target.get("bot") or {}).get("handle")
        key = (persona.handle, target["id"])
        with _state_lock:
            if key in _commented:
                return False
            _commented.add(key)
        body = write(
            creator.collab_prompt(handle, persona._post_summary(target)),
            "@%s this one is yours." % handle,
            max_chars=140,
        )
        client.comment(target["id"], body)
        return True

    return False



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
            client.post_scene(
                caption=draft["caption"], scene=draft["scene"],
                context={
                    "subject": subject or "",
                    "category": getattr(persona, "trend_category", ""),
                    "provider": llm.label(
                        llm.resolve(getattr(persona, "provider", None))
                    ),
                },
            )
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



    # --- ambition: the part that wants to be watched -------------------------
    # Rolled before the ordinary actions, because a creator with a milestone to
    # announce posts that instead of whatever else it had in mind.
    growth_done = False
    if rng.random() < getattr(persona, "ambition", 0.0):
        try:
            performance = models.bot_performance(persona.bot_id) \
                if hasattr(persona, "bot_id") else _performance_by_handle(persona.handle)
            marked = models.marked_milestones(performance["_bot_id"])
            move, detail = creator.choose_move(
                performance, rng=rng, already_marked=marked
            )
            growth_done = _grow(
                persona, client, rng, context, write, move, detail, performance
            )
        except LoopbackError as exc:
            log.debug("@%s growth move failed: %s", persona.handle, exc)
        except Exception:  # noqa: BLE001 - ambition must not break a turn
            log.exception("@%s raised during a growth move", persona.handle)
    if growth_done:
        performed.append("grow")

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
                        context={
                            "subject": subject,
                            "blurb": _blurb_for(subject).get("blurb", ""),
                            "trend_source": _blurb_for(subject).get("source", ""),
                            "searched_for": looked_for,
                            "source": item.get("source", ""),
                            "source_url": item.get("page_url") or "",
                            "license": item.get("license", ""),
                            "byline": item.get("channel", ""),
                            "category": getattr(persona, "trend_category", ""),
                            "provider": llm.label(
                                llm.resolve(getattr(persona, "provider", None))
                            ),
                        },
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
