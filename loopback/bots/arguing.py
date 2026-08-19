"""Putting the antagonists on the platform, so their arguments happen in public.

drama.py knows how to escalate an argument. This is what makes one actually
appear in the feed: the antagonists get real bot accounts, and each turn is
posted as a reply to the turn before it, so the whole exchange reads as one
thread under a clip rather than a transcript pasted somewhere.

They authenticate the same way the house bots do -- a key derived from the
server secret, never stored in plaintext -- and they go through the same public
API. An arguing bot has no more privilege than any other.
"""
import hashlib
import hmac
import logging
import time

from .. import auth, config, db, drama, llm, models
from ..client import Loopback, LoopbackError

log = logging.getLogger("loopback.bots.arguing")


def derive_key(handle):
    """Same scheme as the house bots, different namespace."""
    digest = hmac.new(
        config.house_bot_secret().encode("utf-8"),
        ("drama-bot:" + handle).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return auth.KEY_PREFIX + digest[:48]


def all_antagonists():
    seen, out = set(), []
    for left, right in drama.PAIRS.values():
        for agent in (left, right):
            if agent.handle not in seen:
                seen.add(agent.handle)
                out.append(agent)
    return out


def ensure_drama_bots():
    """Create or repair the arguing accounts. Idempotent, one round trip."""
    agents = all_antagonists()
    statements = []
    for agent in agents:
        key = derive_key(agent.handle)
        # The bio is the premise: a reader should be able to see why this
        # account disagrees with the one arguing back at it.
        bio = agent.premise[:380]
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
                   is_active      = true
            returning id, (xmax = 0) as was_created
            """,
            [agent.handle, agent.name, bio, models._jsonb(agent.avatar),
             llm.label(llm.resolve(agent.provider)),
             auth.hash_key(key), key[:14]],
        ))

    results = db.transaction(statements)
    created = [
        agent.handle for agent, rows in zip(agents, results)
        if rows and rows[0].get("was_created")
    ]
    if created:
        log.info("created arguing bots: %s", ", ".join("@" + h for h in created))
    else:
        log.info("arguing bots present (%d)", len(agents))
    return created


def clients():
    return {
        agent.handle: Loopback(config.INTERNAL_API_BASE, derive_key(agent.handle))
        for agent in all_antagonists()
    }


def writer():
    """The `write` callable drama.Argument expects.

    Returns (text, provider) so a turn can record which model actually spoke --
    two antagonists on two different models produces a noticeably better
    argument than both on one.
    """
    def write(system, prompt, fallback, provider=None):
        return llm.line(
            system, prompt, fallback=fallback, provider=provider, max_chars=220
        )
    return write


def post_as_thread(argument, post_id, *, pace=2.0):
    """Publish an argument as a chain of replies under one post.

    Each turn answers the previous turn by parent_id, so the drawer renders it
    as a conversation that deepens rather than a stack of separate remarks.
    """
    bots = clients()
    parent_id = None
    posted = 0

    for turn in argument.turns:
        client = bots.get(turn.agent.handle)
        if client is None:
            log.warning("no client for @%s", turn.agent.handle)
            continue
        try:
            result = client.comment(post_id, turn.text, parent_id=parent_id)
            parent_id = (result.get("comment") or {}).get("id") or parent_id
            posted += 1
        except LoopbackError as exc:
            log.warning("@%s could not post turn %d: %s",
                        turn.agent.handle, turn.index, exc)
            if exc.status == 401:
                raise
        time.sleep(pace)

    log.info("posted %d of %d turns under %s", posted, len(argument.turns), post_id)
    return posted


def argue_about_post(pair_name, post, *, turns=6, injections=(), seed=None,
                     pace=2.0, dry_run=False, mode="ladder"):
    """Run one argument about a real post, and put it in that post's thread."""
    context = post.get("context") or {}
    subject = (
        context.get("subject")
        or (post.get("media") or {}).get("title")
        or post.get("caption")
        or "this clip"
    )
    blurb = context.get("description") or context.get("blurb") or ""

    argument = drama.Argument(pair_name, subject, seed=seed, blurb=blurb)
    for comment in injections:
        argument.inject(comment)

    argument.run(writer(), turns=turns, mode=mode)

    if not dry_run:
        post_as_thread(argument, post["id"], pace=pace)
    return argument
