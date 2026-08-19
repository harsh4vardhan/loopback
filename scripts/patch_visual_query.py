"""Search for footage that exists, not for the subject's name.

Stock libraries are indexed by what is visibly in the frame, not by proper
nouns. Searching "Von Miller" returns whatever Pexels thinks is closest, which
is why a caption naming a person sat over unrelated footage.

So the subject is translated into a short visual query first -- the concrete
things a camera could have pointed at -- and the caption is then written about
what the clip actually shows, while still being prompted by the subject that
started it. The translation is one cheap LLM call and falls back to the raw
subject when no model is reachable.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    '''def post_subject(post):''',
    '''# Named entities that stock libraries will not have footage of. Mapping these
# to what a camera could actually see is the difference between a clip that
# matches its caption and one that merely shares a word with it.
_VISUAL_PROMPT = (
    "Turn this subject into a short stock-footage search query: %r.\\n"
    "Stock libraries are indexed by what is visible in the frame, not by names. "
    "Reply with two to four concrete, filmable nouns -- places, objects, "
    "materials, weather, activities. No names of people, brands, titles or "
    "companies. No punctuation. Example: for 'Von Miller' reply "
    "'american football stadium floodlights'."
)


def visual_query(subject, write):
    """A search string a stock library can actually answer."""
    if not subject:
        return None
    query = write(_VISUAL_PROMPT % subject, subject, max_chars=60)
    query = " ".join(str(query or "").replace(",", " ").split())[:60]
    return query or subject


def post_subject(post):''',
)

# Forage: translate first, search on the translation, caption from both.
s = s.replace(
    '''        if subject:
            with _state_lock:
                seen = set(_posted_urls)
            item = discovery.pick(subject, rng=rng, exclude=seen)''',
    '''        if subject:
            with _state_lock:
                seen = set(_posted_urls)
            looked_for = visual_query(subject, write) or subject
            item = discovery.pick(looked_for, rng=rng, exclude=seen)
            if item is None and looked_for != subject:
                # The translation may have been too specific; try the subject.
                item = discovery.pick(subject, rng=rng, exclude=seen)''',
)

s = s.replace(
    '''                    caption = persona.make_forage_caption(
                        rng, item, write, subject=subject
                    )''',
    '''                    caption = persona.make_forage_caption(
                        rng, item, write, subject=subject, shows=looked_for
                    )''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py patched")

# --- personas: caption what is visible, prompted by the subject ------------
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
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
    '''    def make_forage_caption(self, rng, item, write, *, subject=None, shows=None):
        """Caption for a clip this bot found rather than made.

        `subject` is what the bot was thinking about; `shows` is what the clip
        actually depicts, which is rarely the same thing -- a stock library has
        no footage of a named person, only of the scene around them. The caption
        is written about what is visible, with the subject as the reason it was
        looked for.
        """
        visible = shows or item.get("title") or subject or "something"
        prompt = (
            "You were thinking about %s, went looking, and found a clip that "
            "shows: %s. Write one line to sit directly under this clip. Describe "
            "what is on screen -- %s -- in your own voice. Do not name %s "
            "unless the footage would obviously show it. %s"
            % (subject or visible, visible, visible, subject or visible,
               TOPIC_GUARDRAIL)
        )
        return write(prompt, "%s." % str(visible)[:110])''',
)

p.write_text(s, encoding="utf-8")
print("personas.py patched")

for f, markers in ((r, ["visual_query", "looked_for", "_VISUAL_PROMPT"]),
                   (p, ["shows=None", "what is on screen"])):
    text = f.read_text(encoding="utf-8")
    for m in markers:
        print("  %-18s %s" % (m, "present" if m in text else "MISSING"))
