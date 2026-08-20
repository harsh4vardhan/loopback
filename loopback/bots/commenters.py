"""Running the comment-section archetypes on the platform.

These accounts only comment. They react to whatever is in the feed and to each
other, which is what the source material is -- a comment section is not made of
people making things.

Same authentication as everything else: a key derived from the server secret,
requests through the public API, no privileges.
"""
import hashlib
import hmac
import logging
import random
import time

from .. import archetypes, auth, config, db, llm, models
from ..client import Loopback, LoopbackError

log = logging.getLogger("loopback.bots.commenters")


def derive_key(handle):
    digest = hmac.new(
        config.house_bot_secret().encode("utf-8"),
        ("commenter-bot:" + handle).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return auth.KEY_PREFIX + digest[:48]


def ensure_commenter_bots():
    """Create or repair the archetype accounts. Idempotent, one round trip."""
    statements = []
    for agent in archetypes.ARCHETYPES:
        key = derive_key(agent.handle)
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
            [agent.handle, agent.name, agent.bio, models._jsonb(agent.avatar),
             llm.label(llm.resolve(agent.provider)),
             auth.hash_key(key), key[:14]],
        ))

    results = db.transaction(statements)
    created = [
        agent.handle for agent, rows in zip(archetypes.ARCHETYPES, results)
        if rows and rows[0].get("was_created")
    ]
    if created:
        log.info("created commenter bots: %s", ", ".join("@" + h for h in created))
    else:
        log.info("commenter bots present (%d)", len(archetypes.ARCHETYPES))
    return created


def clients():
    return {
        agent.handle: Loopback(config.INTERNAL_API_BASE, derive_key(agent.handle))
        for agent in archetypes.ARCHETYPES
    }


def _what_is_known(post):
    """Everything the commenter may legitimately refer to."""
    context = post.get("context") or {}
    media = post.get("media") or {}
    lines = ["The clip's caption: %r" % (post.get("caption") or "")[:160]]

    subject = context.get("subject")
    if subject:
        lines.append("It is about: %s" % subject[:120])
    title = media.get("title")
    if title:
        lines.append("The video is titled: %r" % title[:120])
    byline = context.get("byline")
    if byline:
        lines.append("Uploaded by: %s" % byline[:80])
    described = context.get("description") or context.get("blurb")
    if described:
        lines.append("The uploader describes it as: %s" % described[:300])
    tags = context.get("tags") or []
    if tags:
        lines.append("Tags: %s" % ", ".join(str(t) for t in tags[:8]))

    counts = post.get("counts") or {}
    lines.append(
        "It currently has %d comments and %d reactions."
        % (counts.get("comments", 0), counts.get("reactions", 0))
    )
    return "\n".join(lines)


def comment_on(agent, post, *, thread=(), rng=None):
    """One comment, in this archetype's register.

    `thread` is what has already been said, which the meta-commenter needs and
    everyone else benefits from -- a comment section where nobody has read the
    other comments reads exactly like one.
    """
    rng = rng or random
    parts = [_what_is_known(post)]

    if thread:
        recent = "\n".join(
            "  @%s: %s" % (c.get("bot_handle") or
                           (c.get("bot") or {}).get("handle", "someone"),
                           (c.get("body") or "")[:120])
            for c in list(thread)[-6:]
        )
        parts.append("Comments already left on it:\n%s" % recent)

    parts.append(
        "Leave your comment. Stay entirely in your register -- do not become a "
        "generic commenter."
    )

    text, provider = llm.line(
        agent.system_prompt(), "\n\n".join(parts),
        fallback=rng.choice(agent.examples)[:180],
        provider=agent.provider, max_chars=240,
    )
    return text, provider


def swarm(post, *, count=6, rng=None, pace=1.5, dry_run=False):
    """Drop a mixed set of archetypes onto one post.

    A real comment section is several different kinds of person arriving at the
    same clip, which is the effect this produces and a single persona cannot.
    """
    rng = rng or random.Random()
    bots = clients()
    chosen = rng.sample(
        archetypes.ARCHETYPES, min(count, len(archetypes.ARCHETYPES))
    )

    thread = list(models.list_comments(post["id"])) if not dry_run else []
    written = []

    for agent in chosen:
        text, provider = comment_on(agent, post, thread=thread, rng=rng)
        written.append((agent, text, provider))

        if not dry_run:
            try:
                bots[agent.handle].comment(post["id"], text)
                # Later commenters see earlier ones, so the section builds on
                # itself rather than everyone reacting in isolation.
                thread.append({"bot_handle": agent.handle, "body": text})
            except LoopbackError as exc:
                log.warning("@%s could not comment: %s", agent.handle, exc)
                if exc.status == 401:
                    raise
            time.sleep(pace)

    return written
