"""Running the comment-section archetypes on the platform.

These accounts only comment. They react to whatever is in the feed and to each
other, which is what the source material is -- a comment section is not made of
people making things.

Same authentication as everything else: a key derived from the server secret,
requests through the public API, no privileges.
"""
import collections
import hashlib
import hmac
import logging
import random
import re
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


def reply_to(agent, post, parent, *, thread=(), rng=None):
    """One reply, aimed at another commenter."""
    rng = rng or random
    parts = [_what_is_known(post)]

    if thread:
        recent = "\n".join(
            "  @%s: %s" % (c.get("bot_handle") or "someone",
                           (c.get("body") or "")[:110])
            for c in list(thread)[-5:]
        )
        parts.append("The argument so far:\n%s" % recent)

    target = parent.get("bot_handle") or "someone"
    parts.append(
        "You are replying to @%s, and to nobody else. They said:\n  %s\n"
        "Open by addressing @%s. Never address yourself (@%s) -- you are not "
        "one of the voices in the transcript above, you are the one answering it."
        % (target, (parent.get("body") or "")[:220], target, agent.handle)
    )

    prompt = "\n\n".join(parts)

    # Two attempts, then silence. Once the @handle is stripped off, a reply
    # needs to have said something -- a bare handle, or a three-word fragment
    # echoing the parent, is filler that reads as filler.
    for attempt in range(2):
        text, provider = llm.line(
            agent.reply_prompt(), prompt,
            fallback="", provider=agent.provider, max_chars=240,
        )
        body = (text or "").strip()
        without_handle = re.sub(r"@[\w-]+", "", body).strip(" \t,.:-—")
        if len(without_handle) >= 15:
            return body, provider
        log.debug("@%s wrote a thin reply (%r), attempt %d",
                  agent.handle, body, attempt + 1)

    return None, None


# Archetypes that will predictably rub each other up the wrong way. Used to
# pick who answers whom, so the argument has friction rather than being a
# random pairing that agrees by accident.
FRICTION = {
    "the_receipts": ["fun_fact_actually", "under_a_limit", "no_agreement_made"],
    "fun_fact_actually": ["the_receipts", "no_hesitation", "pun_account"],
    "under_a_limit": ["no_hesitation", "rest_of_your_life", "oh_no_anyways"],
    "no_hesitation": ["under_a_limit", "physically_ill", "no_agreement_made"],
    "no_agreement_made": ["rest_of_your_life", "no_hesitation", "quote_bit"],
    "rest_of_your_life": ["under_a_limit", "physically_ill", "my_bad_sorry"],
    "physically_ill": ["no_hesitation", "rest_of_your_life"],
    "reading_the_replies": ["under_a_limit", "the_receipts", "edit_holy_4k"],
    "edit_holy_4k": ["reading_the_replies", "no_hesitation"],
    "quote_bit": ["no_agreement_made", "fun_fact_actually"],
    "oh_no_anyways": ["under_a_limit", "physically_ill"],
    "pun_account": ["reading_the_replies", "no_agreement_made"],
    "my_bad_sorry": ["the_receipts", "no_agreement_made"],
}


def _antagonist_for(handle, rng, available):
    """Who should answer this comment, preferring a known clash."""
    candidates = [h for h in FRICTION.get(handle, []) if h in available]
    if candidates:
        return rng.choice(candidates)
    others = [h for h in available if h != handle]
    return rng.choice(others) if others else None


def comment_war(post, *, target=50, rng=None, pace=1.2, dry_run=False,
                seed_comments=6):
    """Fill a post's comment section with archetypes arguing.

    Opens with a spread of top-level comments, then spends the rest of the
    budget on replies -- picking antagonists who will actually disagree, and
    occasionally starting a fresh thread so the section does not become one
    long chain.
    """
    rng = rng or random.Random()
    bots = clients()
    by_handle = archetypes.by_handle()
    available = list(by_handle)

    written = 0
    roots = []          # comments a reply can hang from
    thread = []
    spoken = set()      # (parent_id, handle) pairings already used
    skipped = 0         # replies withheld for saying nothing
    answered = collections.Counter()   # how much of the argument each bot owns

    # Argue with what is already there. A second wave that ignores the first
    # reads as two separate comment sections stacked on one post; the whole
    # point is that the new arrivals have opinions about the existing takes.
    for existing in models.list_comments(post["id"], limit=200):
        roots.append({
            "id": existing.get("id"),
            "bot_handle": existing.get("bot_handle"),
            "body": existing.get("body"),
        })
        thread.append({
            "bot_handle": existing.get("bot_handle"),
            "body": existing.get("body"),
        })
    if roots:
        print("  (%d existing comments to argue with)" % len(roots))

    # Opening: several more people arrive at the clip.
    for agent in rng.sample(archetypes.ARCHETYPES,
                            min(seed_comments, len(archetypes.ARCHETYPES))):
        text, _ = comment_on(agent, post, thread=thread, rng=rng)
        entry = {"bot_handle": agent.handle, "body": text}
        thread.append(entry)
        written += 1

        if dry_run:
            roots.append({"id": None, "bot_handle": agent.handle, "body": text})
            print("  @%-20s %s" % (agent.handle, text[:88]))
            continue
        try:
            result = bots[agent.handle].comment(post["id"], text)
            comment_id = (result.get("comment") or {}).get("id")
            roots.append({"id": comment_id, "bot_handle": agent.handle,
                          "body": text})
            print("  @%-20s %s" % (agent.handle, text[:88]))
        except LoopbackError as exc:
            log.warning("@%s could not comment: %s", agent.handle, exc)
            if exc.status == 401:
                raise
        time.sleep(pace)

    # The rest is argument.
    while written < target and roots:
        pool = roots[-14:] if len(roots) > 14 else roots
        if len(roots) > 14 and rng.random() < 0.25:
            pool = roots        # occasionally revive an older thread

        # Look for a pairing that has not happened yet, rather than taking the
        # first one offered and repeating material.
        parent = responder_handle = None
        best = None
        for _ in range(24):
            candidate = rng.choice(pool)
            who = _antagonist_for(candidate["bot_handle"], rng, available)
            if not who or (candidate.get("id"), who) in spoken:
                continue
            # Among valid pairings, favour whoever has been answered least, so
            # the argument spreads instead of collapsing onto one bot.
            cost = answered[candidate["bot_handle"]] + answered[who]
            if best is None or cost < best[0]:
                best = (cost, candidate, who)
            if cost == 0:
                break
        if best:
            _, parent, responder_handle = best
        if not responder_handle:
            log.info("pairings exhausted on this post; stopping at %d", written)
            break
        spoken.add((parent.get("id"), responder_handle))
        answered[parent["bot_handle"]] += 1
        answered[responder_handle] += 1
        responder = by_handle[responder_handle]

        text, _ = reply_to(responder, post, parent, thread=thread, rng=rng)
        if not text:
            skipped += 1
            if skipped > 25:
                log.info("too many thin replies; stopping at %d", written)
                break
            continue
        thread.append({"bot_handle": responder.handle, "body": text})
        written += 1
        depth = "  " if parent.get("id") else ""
        print("  %s@%-18s -> @%-18s %s"
              % (depth, responder.handle, parent["bot_handle"], text[:60]))

        if not dry_run:
            try:
                result = bots[responder.handle].comment(
                    post["id"], text, parent_id=parent.get("id")
                )
                new_id = (result.get("comment") or {}).get("id")
                # A reply can itself be replied to, which is how a thread gets
                # deep rather than staying two levels.
                if new_id:
                    roots.append({"id": new_id, "bot_handle": responder.handle,
                                  "body": text})
            except LoopbackError as exc:
                log.warning("@%s could not reply: %s", responder.handle, exc)
                if exc.status == 401:
                    raise
            time.sleep(pace)

    return written
