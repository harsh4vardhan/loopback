"""Make the caption describe the clip that was actually posted.

The bug: a turn drew a subject twice, independently. _background() picked one
to read up on, and the forage block picked another to search footage for. The
prompt therefore carried background about subject A while the attached video
was of subject B, so captions read as unrelated to the clip.

The fix: draw the subject once per turn and thread it through both, and hand
the subject to make_forage_caption so the prompt names the thing on screen
rather than only the stock library's title for it.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- runtime: one subject per turn ----------------------------------------
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    '''def _background(persona, rng):
    """One subject this bot has "read up on" this turn, as a short brief.

    Returns a string to append to prompts, or "". Cached inside trends, so a
    tick costs at most one extra request and usually none.
    """
    try:
        trend = trends.pick(getattr(persona, "trend_category", "anything"), rng=rng)
        subject = trend["subject"] if trend else None
        if not subject and getattr(persona, "topics", None):
            subject = rng.choice(list(persona.topics))
        if not subject:
            return ""

        note = trends.context(subject)
        if not note:
            # Still worth naming the subject even without a summary: it gives
            # the bot something current to be preoccupied with.
            return "\\n\\nSomething on your mind right now: %s. %s" % (
                subject, trends.TOPIC_GUARDRAIL)
        return (
            "\\n\\nBackground you have just read about %s: %s\\n%s"
            % (note["subject"], note["summary"], trends.TOPIC_GUARDRAIL)
        )
    except Exception:  # noqa: BLE001 - grounding is a bonus, never a blocker
        log.debug("no background for @%s", persona.handle)
        return ""''',
    '''def _subject_and_background(persona, rng):
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
            return subject, "\\n\\nSomething on your mind right now: %s. %s" % (
                subject, trends.TOPIC_GUARDRAIL)
        return subject, (
            "\\n\\nBackground you have just read about %s: %s\\n%s"
            % (note["subject"], note["summary"], trends.TOPIC_GUARDRAIL)
        )
    except Exception:  # noqa: BLE001 - grounding is a bonus, never a blocker
        log.debug("no background for @%s", persona.handle)
        return None, ""''',
)

s = s.replace(
    '''    used_providers = set()
    # Only pay for a lookup if this bot is going to open its mouth this turn.
    will_speak = (
        rng.random() < persona.post_chance + persona.comment_chance
        + getattr(persona, "reply_chance", 0) + getattr(persona, "forage_chance", 0)
    )
    write = _writer(
        persona, used_providers, _background(persona, rng) if will_speak else ""
    )''',
    '''    used_providers = set()
    # Only pay for a lookup if this bot is going to open its mouth this turn.
    will_speak = (
        rng.random() < persona.post_chance + persona.comment_chance
        + getattr(persona, "reply_chance", 0) + getattr(persona, "forage_chance", 0)
    )
    subject, background = (
        _subject_and_background(persona, rng) if will_speak else (None, "")
    )
    write = _writer(persona, used_providers, background)''',
)

# The forage block reuses the turn's subject instead of drawing another.
s = s.replace(
    '''    if rng.random() < getattr(persona, "forage_chance", 0.0):
        subject = None
        trend = trends.pick(
            getattr(persona, "trend_category", "anything"), rng=rng
        )
        if trend:
            subject = trend["subject"]
        elif getattr(persona, "topics", None):
            subject = rng.choice(list(persona.topics))

        if subject:''',
    '''    if rng.random() < getattr(persona, "forage_chance", 0.0):
        # Deliberately the same subject the bot was just briefed on, so the
        # caption and the footage are about one thing.
        if subject:''',
)

s = s.replace(
    '''                    caption = persona.make_forage_caption(rng, item, write)''',
    '''                    caption = persona.make_forage_caption(
                        rng, item, write, subject=subject
                    )''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py patched")

# --- personas: name the subject in the caption prompt ----------------------
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    '''    def make_forage_caption(self, rng, item, write):
        """Caption for a clip this bot found on the open web rather than made."""
        return write(
            "You found footage titled %r from %s. Write one line introducing it "
            "in your own voice. %s" % (
                item.get("title", "untitled"), item.get("source", "somewhere"),
                TOPIC_GUARDRAIL,
            ),
            "found this. %s" % item.get("title", "")[:120],
        )''',
    '''    def make_forage_caption(self, rng, item, write, *, subject=None):
        """Caption for a clip this bot found on the open web rather than made.

        The subject matters more than the library's title: stock footage is
        often labelled thinly or not at all, and the caption should describe
        what the viewer is about to watch.
        """
        title = item.get("title") or ""
        described = subject or title or "something"
        detail = (" The library labels it %r." % title) if title and title != subject else ""

        return write(
            "You went looking for footage of %s and found a clip from %s.%s "
            "Write one line introducing it, in your own voice. Write about %s "
            "specifically -- the caption sits directly under this clip, so it "
            "must describe what is on screen. %s" % (
                described, item.get("source", "somewhere"), detail,
                described, TOPIC_GUARDRAIL,
            ),
            "%s. found footage." % described[:110],
        )''',
)

p.write_text(s, encoding="utf-8")
print("personas.py patched")

for f, markers in (
    (r, ["_subject_and_background", "subject=subject", "same subject the bot"]),
    (p, ["subject=None", "must describe what is on screen"]),
):
    text = f.read_text(encoding="utf-8")
    for m in markers:
        print("  %-34s %s" % (m[:34], "present" if m in text else "MISSING"))
