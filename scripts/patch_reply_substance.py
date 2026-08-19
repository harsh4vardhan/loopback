"""Let a replying bot see the story, not just the search term.

Posting was fixed to use the wire's own summary; replying was not. A bot
commenting on someone else's clip still looked the subject up on Wikipedia,
which returns nothing for a headline, so it fell back to describing what was on
screen -- hence "that 31 days font is gonna delaminate" under a post about
rough sleepers.

The summary is now carried on the post itself, in the context document that
already had a `blurb` field going unused. A replying bot reads it and argues
with the story.
"""
import pathlib

r = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

# _subject_and_background also hands back the summary it found.
s = s.replace(
    '''        blurb = (trend or {}).get("blurb") or ""
        source = (trend or {}).get("source") or ""
        if blurb:
            return subject, (
                "\\n\\nYou have just read this, from %s:\\n%s\\n%s\\n%s"
                % (source or "a news feed", subject, blurb,
                   trends.TOPIC_GUARDRAIL)
            )

        note = trends.context(subject)
        if not note:
            return subject, (
                "\\n\\nYou have just read a headline from %s: %s\\n%s"
                % (source or "a news feed", subject, trends.TOPIC_GUARDRAIL)
            )
        return subject, (
            "\\n\\nBackground you have just read about %s: %s\\n%s"
            % (note["subject"], note["summary"], trends.TOPIC_GUARDRAIL)
        )''',
    '''        blurb = (trend or {}).get("blurb") or ""
        source = (trend or {}).get("source") or ""
        if blurb:
            _remember_blurb(subject, blurb, source)
            return subject, (
                "\\n\\nYou have just read this, from %s:\\n%s\\n%s\\n%s"
                % (source or "a news feed", subject, blurb,
                   trends.TOPIC_GUARDRAIL)
            )

        note = trends.context(subject)
        if not note:
            return subject, (
                "\\n\\nYou have just read a headline from %s: %s\\n%s"
                % (source or "a news feed", subject, trends.TOPIC_GUARDRAIL)
            )
        _remember_blurb(subject, note["summary"], "Wikipedia")
        return subject, (
            "\\n\\nBackground you have just read about %s: %s\\n%s"
            % (note["subject"], note["summary"], trends.TOPIC_GUARDRAIL)
        )''',
)

s = s.replace(
    '''def _subject_and_background(persona, rng):''',
    '''# The summary behind the subject a bot is currently posting about, so it can be
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


def _subject_and_background(persona, rng):''',
)

# Attach it to the forage post.
s = s.replace(
    '''                        context={
                            "subject": subject,
                            "searched_for": looked_for,''',
    '''                        context={
                            "subject": subject,
                            "blurb": _blurb_for(subject).get("blurb", ""),
                            "trend_source": _blurb_for(subject).get("source", ""),
                            "searched_for": looked_for,''',
)

# And read it back when replying.
s = s.replace(
    '''def _post_background(post):
    """A brief about someone else's clip, for commenting on it."""
    subject = post_subject(post)
    if not subject:
        return ""
    try:
        note = trends.context(subject)
    except Exception:  # noqa: BLE001
        note = None
    if not note:
        return ("\\n\\nThe clip you are looking at is footage of %s. Your reply "
                "must be about that." % subject)
    return (
        "\\n\\nThe clip you are looking at is footage of %s. Background you know "
        "about it: %s\\nYour reply must be about what is on screen. %s"
        % (subject, note["summary"], trends.TOPIC_GUARDRAIL)
    )''',
    '''def _post_background(post):
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
            "\\n\\nThe post you are replying to is about: %s\\nYour reply must be "
            "about that subject, not about what the footage looks like. %s"
            % (subject, trends.TOPIC_GUARDRAIL)
        )
    return (
        "\\n\\nThe post you are replying to is about: %s\\nWhat you know about it"
        "%s: %s\\nReply about the subject -- react to it, push back on it, or ask "
        "something real about it. Do not just describe the footage. %s"
        % (subject, (" (from %s)" % source) if source else "", blurb,
           trends.TOPIC_GUARDRAIL)
    )''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py patched")
for marker in ("_remember_blurb", "_blurb_for", "not about what the footage looks like"):
    print("  %-38s %s" % (marker[:38], "present" if marker in s else "MISSING"))
