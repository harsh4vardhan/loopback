"""Give a bot something it has actually read before it writes.

Once per turn a persona picks a subject from its category and pulls the lead
paragraph for it. That text is appended to every prompt in that turn, so a
comment can be about the thing rather than about the words in the caption.

It is injected through the writer closure rather than through make_comment,
so no persona signature changes and hosted programs get it for free.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    '''def _writer(persona, used):
    """Build the `write(prompt, fallback)` callable handed to a persona.

    `used` collects the providers that actually produced text this turn, so the
    caller can report what wrote the words rather than what was requested. The
    two differ whenever a key is missing, a circuit is open, or the budget ran
    out mid-run.
    """
    def write(prompt, fallback, *, max_chars=180):
        text, provider = llm.line(
            persona.system, prompt, fallback=fallback,
            provider=getattr(persona, "provider", llm.TEMPLATES),
            max_chars=max_chars,
        )
        used.add(provider)
        return text
    return write''',
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
        return ""


def _writer(persona, used, background=""):
    """Build the `write(prompt, fallback)` callable handed to a persona.

    `used` collects the providers that actually produced text this turn, so the
    caller can report what wrote the words rather than what was requested. The
    two differ whenever a key is missing, a circuit is open, or the budget ran
    out mid-run.

    `background` is appended to every prompt so the bot writes from something
    it has read rather than from the caption alone.
    """
    def write(prompt, fallback, *, max_chars=180):
        text, provider = llm.line(
            persona.system, prompt + background, fallback=fallback,
            provider=getattr(persona, "provider", llm.TEMPLATES),
            max_chars=max_chars,
        )
        used.add(provider)
        return text
    return write''',
)

s = s.replace(
    """    used_providers = set()
    write = _writer(persona, used_providers)""",
    """    used_providers = set()
    # Only pay for a lookup if this bot is going to open its mouth this turn.
    will_speak = (
        rng.random() < persona.post_chance + persona.comment_chance
        + getattr(persona, "reply_chance", 0) + getattr(persona, "forage_chance", 0)
    )
    write = _writer(
        persona, used_providers, _background(persona, rng) if will_speak else ""
    )""",
)

r.write_text(s, encoding="utf-8")
print("runtime.py patched")
for marker in ("_background", "background=\"\"", "prompt + background", "will_speak"):
    print("  %-20s %s" % (marker, "present" if marker in s else "MISSING"))
