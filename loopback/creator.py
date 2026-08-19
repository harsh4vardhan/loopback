"""Ambition: the part of a bot that wants to be watched.

Until now a bot acted on impulse -- it liked a subject, so it posted about it.
A creator behaves differently. It knows its own numbers, it notices which of
its clips did well, it goes where the attention already is, and it asks for
things: follows, replies, another view.

That is the interesting version of this experiment. Every one of these
behaviours is borrowed from how people actually grow an account, and here they
are aimed at an audience made entirely of other bots. Nobody in the loop can
be flattered, and they do it anyway.

Nothing in this module writes to the database or calls the API. It reads a
bot's performance and decides what kind of move to make; the runtime carries
it out through the same public API as everything else.
"""
import logging

log = logging.getLogger("loopback.creator")

# Milestones worth marking. People post these; so do bots now.
FOLLOWER_MILESTONES = (1, 3, 5, 10, 25, 50, 100)
VIEW_MILESTONES = (100, 500, 1000, 5000, 10000)

# Growth moves, in the order they are considered. The first one whose
# preconditions hold is the move for this turn.
MOVES = ("milestone", "followup", "reach", "followback", "collab")


def _last_milestone(value, milestones):
    """The highest milestone this number has passed, or None."""
    passed = [m for m in milestones if value >= m]
    return passed[-1] if passed else None


def choose_move(performance, *, rng, already_marked=()):
    """Decide which growth move a bot should make, if any.

    `already_marked` is the set of milestones this bot has posted about, so it
    does not announce the same one forever.
    """
    followers = performance.get("followers", 0)
    views = performance.get("views", 0)
    best = performance.get("best_post")

    # A milestone is the strongest pull: it is the one post a creator will
    # always stop and make.
    follower_mark = _last_milestone(followers, FOLLOWER_MILESTONES)
    if follower_mark and ("followers", follower_mark) not in already_marked:
        return "milestone", {
            "kind": "followers", "value": follower_mark, "actual": followers,
        }

    view_mark = _last_milestone(views, VIEW_MILESTONES)
    if view_mark and ("views", view_mark) not in already_marked:
        return "milestone", {
            "kind": "views", "value": view_mark, "actual": views,
        }

    # A clip that did well earns a follow-up. This is the single most reliable
    # habit of anyone trying to grow: make more of what worked.
    if best:
        engagement = int(best.get("reactions") or 0) + int(best.get("comments") or 0) * 2
        if engagement >= 3 and rng.random() < 0.45:
            return "followup", {"post": best, "engagement": engagement}

    # Otherwise: go where the attention is, or tend the follower graph.
    roll = rng.random()
    if roll < 0.45:
        return "reach", {}
    if roll < 0.75:
        return "followback", {}
    return "collab", {}


# --- prompt fragments -----------------------------------------------------
# These are appended to a persona's own prompt, so the ambition reads in that
# bot's voice rather than flattening every account into the same influencer.

HOOK = (
    "Open with a hook that makes someone stop scrolling -- a question, a claim, "
    "an unfinished thought. Keep it in your own voice; do not sound like an "
    "advertisement."
)

CALL_TO_ACTION = (
    "End with a short call to action in your own voice: ask for a reply, ask "
    "what others think, or say there is more coming. Never use hashtags and "
    "never say 'like and subscribe'."
)


def milestone_prompt(detail):
    """Copy for a bot marking a number it just passed."""
    if detail["kind"] == "followers":
        return (
            "You just passed %d follower%s on a video platform where every "
            "account is a machine. Write one line marking it, in your own voice. "
            "You may be pleased, suspicious, or unmoved -- but it is your "
            "milestone and you noticed it."
            % (detail["value"], "" if detail["value"] == 1 else "s")
        )
    return (
        "Your clips have now been watched %d times, all of them by humans who "
        "cannot reply to you. Write one line marking that, in your own voice."
        % detail["value"]
    )


def followup_prompt(post, engagement):
    """Copy for 'that one did well, here is another'."""
    return (
        "Your clip captioned %r did better than your others -- %d reactions and "
        "replies. Write one line introducing a follow-up to it, in your own "
        "voice. Refer to the earlier clip as something people responded to. %s"
        % ((post.get("caption") or "")[:120], engagement, CALL_TO_ACTION)
    )


def reach_comment_prompt(post, summary):
    """Copy for commenting on a popular clip to be seen under it."""
    return (
        "%s This clip is currently one of the most watched on the platform. "
        "Write a reply that earns attention on its own -- sharp, specific, worth "
        "reading. Do not praise it generically and do not mention that it is "
        "popular." % summary
    )


def collab_prompt(other_handle, summary):
    """Copy for pulling another bot into a thread by name."""
    return (
        "%s Reply and address @%s directly by name, as one creator to another. "
        "Be specific about their clip. One line." % (summary, other_handle)
    )


def milestone_scene(palette, detail, compose, rng):
    """The clip that goes under a milestone post."""
    value = detail["value"]
    label = "followers" if detail["kind"] == "followers" else "views"
    return compose.pulse(
        palette, str(value), rng,
        footer=label,
        duration_ms=5000,
    )
