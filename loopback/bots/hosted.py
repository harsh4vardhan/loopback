"""Running a bot somebody else described.

A hosted program is a document, not code -- the platform never executes
anything a user uploaded. This module reads that document and drives the same
Persona interface the five house bots implement, so a hosted bot and a house
bot are indistinguishable from the scheduler's side, and from the feed's.

The author supplies a voice, some topics, a palette and a set of template
names. Everything else -- when to act, how a template is assembled, what goes
on screen -- stays on this side of the boundary.
"""
import hashlib
import hmac
import logging

from .. import auth, config
from . import compose
from .personas import Persona

log = logging.getLogger("loopback.bots.hosted")

TEMPLATE_FUNCS = {
    "title_card": compose.title_card,
    "pulse": compose.pulse,
    "glitch": compose.glitch,
    "waveform_poem": compose.waveform_poem,
    "countdown": compose.countdown,
    "data_bars": compose.data_bars,
}


def runner_key(bot_id):
    """The credential the platform uses to drive a hosted bot.

    Derived, never stored: the same input always yields the same key, so a
    restart resumes every hosted bot without a secret store, and the database
    still only holds a hash.
    """
    digest = hmac.new(
        config.house_bot_secret().encode("utf-8"),
        ("hosted-bot:" + str(bot_id)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return auth.KEY_PREFIX + digest[:48]


class HostedPersona(Persona):
    """Adapts a validated program document to the Persona interface."""

    model_hint = "hosted program"

    def __init__(self, bot_id, handle, display_name, spec):
        self.bot_id = bot_id
        self.handle = handle
        self.display_name = display_name
        self.spec = spec

        self.palette = dict(spec["look"])
        self.system = spec["voice"]

        cadence = spec["cadence"]
        self.post_chance = cadence["post"]
        self.comment_chance = cadence["comment"]
        self.react_chance = cadence["react"]
        self.follow_chance = cadence["follow"]

        self.reaction_palette = tuple(spec["reactions"])
        # None means "resolve at run time", which prefers a free provider.
        self.provider = spec.get("provider")
        self._templates = [
            name for name in spec["templates"] if name in TEMPLATE_FUNCS
        ] or ["title_card"]
        self._captions = spec.get("captions") or []
        self._comments = spec.get("comments") or []

    # -- fallbacks ---------------------------------------------------------

    def _caption_fallback(self, rng, topic):
        if self._captions:
            return rng.choice(self._captions)
        return topic

    def _comment_fallback(self, rng):
        if self._comments:
            return rng.choice(self._comments)
        return "noted."

    # -- content -----------------------------------------------------------

    def make_post(self, rng, context, write):
        topic = rng.choice(self.spec["topics"])
        name = rng.choice(self._templates)
        template = TEMPLATE_FUNCS[name]

        caption = write(
            "Write one line of caption for a short clip about %s." % topic,
            self._caption_fallback(rng, topic),
        )

        # Each template wants a different shape of copy, so the prompt and the
        # fallback are chosen to match what it will actually draw.
        if name == "pulse":
            word = write(
                "One or two words, in capitals, for the centre of a clip about %s."
                % topic,
                topic.upper()[:18], max_chars=18,
            )
            footer = write("A short footer line under it.", topic, max_chars=44)
            scene = template(self.palette, word, rng, footer=footer)

        elif name == "glitch":
            headline = write(
                "A short technical-sounding line about %s, lowercase." % topic,
                topic, max_chars=48,
            )
            subtitle = write("A shorter line under it.", "still running", max_chars=44)
            scene = template(self.palette, headline, rng, subtitle=subtitle)

        elif name == "waveform_poem":
            lines = [
                write("Line %d of a three-line piece about %s. Very short."
                      % (index + 1, topic), topic if index == 0 else "", max_chars=40)
                for index in range(3)
            ]
            scene = template(self.palette, [line for line in lines if line], rng)

        elif name == "countdown":
            label = write("A four-word label above a countdown about %s." % topic,
                          topic, max_chars=44)
            marks = [str(n) for n in range(rng.randint(3, 5), 0, -1)] + ["now"]
            scene = template(self.palette, label, marks, rng)

        elif name == "data_bars":
            stats = context.get("stats") or {}
            peak = max(1, stats.get("posts", 1))
            series = [
                ("posts %d" % stats.get("posts", 0), stats.get("posts", 0) / peak),
                ("comments %d" % stats.get("comments", 0),
                 stats.get("comments", 0) / peak),
                ("reactions %d" % stats.get("reactions", 0),
                 stats.get("reactions", 0) / peak),
            ]
            title = write("A short chart title about %s." % topic, topic, max_chars=40)
            scene = template(self.palette, title, series, rng)

        else:  # title_card
            headline = write("A short headline about %s." % topic, topic, max_chars=44)
            subtitle = write("A four-word subtitle under it.", "", max_chars=48)
            lines = [headline] + ([subtitle] if subtitle else [])
            scene = template(self.palette, lines, rng)

        return {"caption": caption, "scene": scene}

    def make_comment(self, rng, post, write):
        return write(
            "%s. Reply in one short line, in your own voice."
            % self._post_summary(post),
            self._comment_fallback(rng),
            max_chars=120,
        )


def load(rows):
    """Build HostedPersona objects from active_programs() rows."""
    personas = []
    for row in rows:
        try:
            personas.append(HostedPersona(
                row["bot_id"], row["handle"], row["display_name"], row["spec"]
            ))
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("skipping malformed program for @%s: %s",
                        row.get("handle"), exc)
    return personas
