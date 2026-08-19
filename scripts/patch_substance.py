"""Make the post about the subject again, with the footage as illustration.

Two faults, and the first one caused the second.

The briefing was empty for news. _subject_and_background looked every subject up
on Wikipedia, which works for "Grand Theft Auto VI" and fails for "Disabled
people in England to get 24-hour support" -- there is no article by that name.
So for exactly the subjects that had something to say, the bot got nothing but
the headline's wording. Meanwhile the RSS item already carried a summary that
was thrown away. It is now used, and it is better than the Wikipedia lookup for
anything from the wire.

The caption then described the wrong thing. When captions were drifting off
their footage I pushed the prompt to "describe what is on screen", which fixed
the mismatch and broke the point: a political headline became a search term and
never reached the words. A caption now reacts to the subject and uses the
footage as illustration -- it may reference what is visible, but the subject is
what it is about.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- runtime: use the wire's own summary -----------------------------------
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    '''    try:
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
        )''',
    '''    try:
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
)

# The visual query should serve the subject, not replace it.
s = s.replace(
    '''_VISUAL_PROMPT = (
    "Turn this subject into a short stock-footage search query: %r.\\n"
    "Stock libraries are indexed by what is visible in the frame, not by names. "
    "Reply with two to four concrete, filmable nouns -- places, objects, "
    "materials, weather, activities. No names of people, brands, titles or "
    "companies. No punctuation. Example: for 'Von Miller' reply "
    "'american football stadium floodlights'."
)''',
    '''_VISUAL_PROMPT = (
    "You need footage to illustrate this subject: %r.\\n"
    "Stock libraries are indexed by what is visible in the frame, not by names, "
    "so reply with two to four concrete filmable nouns that would make a fitting "
    "backdrop for it -- the setting it happens in, the objects around it, the "
    "weather or light of it. Choose something evocative rather than the most "
    "literal object in the sentence. No names of people, brands, titles or "
    "companies. No punctuation.\\n"
    "Examples: 'Von Miller' -> 'american football stadium floodlights'; "
    "'energy bills drive inflation to a four-month high' -> "
    "'kitchen radiator winter window condensation'."
)''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py: wire summaries used, visual query made evocative")

# --- personas: the caption is about the subject ----------------------------
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    '''        visible = shows or item.get("title") or subject or "something"
        prompt = (
            "You were thinking about %s, went looking, and found a clip that "
            "shows: %s. Write one line to sit directly under this clip. Describe "
            "what is on screen -- %s -- in your own voice. Do not name %s "
            "unless the footage would obviously show it. %s"
            % (subject or visible, visible, visible, subject or visible,
               TOPIC_GUARDRAIL)
        )
        return write(prompt, "%s." % str(visible)[:110])''',
    '''        visible = shows or item.get("title") or subject or "something"
        prompt = (
            "You are posting about: %s\\n"
            "The clip you found shows %s -- that is illustration, not the "
            "point.\\n"
            "Write one line reacting to the SUBJECT in your own voice: what you "
            "make of it, what it reminds you of, what you want to know, what "
            "does not add up. You may nod to what is on screen, but the line "
            "must be about the subject, not a description of the footage. Never "
            "write a caption that would work under any other clip. %s"
            % (subject or visible, visible, TOPIC_GUARDRAIL)
        )
        return write(prompt, "%s." % str(subject or visible)[:110])''',
)

p.write_text(s, encoding="utf-8")
print("personas.py: caption reacts to the subject")

for f, marker in ((r, "You have just read this, from"),
                  (r, "evocative rather than the most"),
                  (p, "that is illustration, not the")):
    print("  %-14s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
