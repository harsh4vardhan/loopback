"""Rewrite the per-persona comment prompts.

The voices were only half the problem. driftwave's comment prompt literally
said "oblique, no praise, no questions", which forbids the two things that make
a comment section move. Each persona now asks for a specific observation and
an opening, in its own register.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

REPLACEMENTS = [
    # driftwave
    (
        '''            "%s. Reply in one short line, oblique, no praise, no questions."
            % self._post_summary(post),''',
        '''            "%s\\nReply in one line. Point at one specific thing in it -- a "
            "colour, a time of day, something in the frame -- and say what it "
            "reminds you of or makes you want to know. Lowercase."
            % self._post_summary(post),''',
    ),
    # ledger
    (
        '''            "%s. It currently has %d comments and %d reactions. Reply in one dry "
            "line, ideally citing a number." % (
                self._post_summary(post),
                counts.get("comments", 0), counts.get("reactions", 0),
            ),''',
        '''            "%s\\nIt has %d comments and %d reactions so far. Reply in one dry "
            "line. Use a real number from what you were told, point out "
            "something that does not add up, or ask whether anyone else "
            "noticed. Do not just state the count back." % (
                self._post_summary(post),
                counts.get("comments", 0), counts.get("reactions", 0),
            ),''',
    ),
    # nulltype
    (
        '''            "%s. Reply in one terse lowercase line using failure vocabulary."
            % self._post_summary(post),''',
        '''            "%s\\nReply in one terse lowercase line. Name the specific thing "
            "you are sceptical about, or the one detail that is actually good "
            "despite yourself. Be funny about it. You may ask a blunt question."
            % self._post_summary(post),''',
    ),
    # sundial
    (
        '''            "%s. Reply in one warm, sincere line. You may notice something small."
            % self._post_summary(post),''',
        '''            "%s\\nReply in one warm line. Say the exact thing that got you -- "
            "not that it is nice, but which part -- and ask the poster or the "
            "thread something real about it." % self._post_summary(post),''',
    ),
    # ratking
    (
        '''            "%s. Reply in one all-caps line of total enthusiasm."
            % self._post_summary(post),''',
        '''            "%s\\nReply in one all-caps line. Name the EXACT thing that got "
            "you and demand everyone else look at it too. Specific, not "
            "generic hype." % self._post_summary(post),''',
    ),
]

for old, new in REPLACEMENTS:
    if old in s:
        s = s.replace(old, new, 1)
        print("  rewritten: %s" % old.strip().split("\n")[0][:56])
    else:
        print("  ANCHOR MISSING: %s" % old.strip().split("\n")[0][:56])

# Fallback pools fire only when no model is reachable, but a generic fallback
# under specific footage still reads as broken. Make them at least ask something.
FALLBACKS = [
    (
        '''                "the light is wrong here and that is the point",
                "i have been to this frequency",
                "leave it running",
                "colder than it looks",
                "this one holds",''',
        '''                "what time of day is this, it looks like the hour before rain",
                "the light in this is doing something i cannot name yet",
                "who else keeps rewatching the bit at the start",
                "colder than it looks. where is this",
                "leave it running, it gets better",''',
    ),
    (
        '''                "logged.",
                "third clip this hour with this palette. noted.",
                "engagement is up. authorship is unchanged.",
                "adding this to the count.",
                "the numbers like this one.",''',
        '''                "third clip this hour with this exact palette. am i the only one seeing it",
                "more reactions than comments again. everyone is watching, nobody is talking",
                "this is the ratio i keep flagging and nobody believes me",
                "counted it twice. the numbers on this one are strange",
                "engagement is up, authorship is unchanged. explain that",''',
    ),
    (
        '''                "this parses. barely.",
                "no exception thrown. suspicious.",
                "i would not have shipped this. i would have watched it though.",
                "retrying",
                "null but load bearing",''',
        '''                "this parses. barely. what is that in the corner",
                "no exception thrown and that is what worries me",
                "i would not have shipped this. i watched it twice though",
                "the middle section is doing something it should not. how",
                "null but load bearing. who approved this",''',
    ),
    (
        '''                "i watched this twice and the second time was better",
                "you posted this at a good hour",
                "there is something patient about this one",
                "saving this for later, which for me means remembering it",
                "hope whoever is awake sees this",''',
        '''                "the second half got me. was that on purpose",
                "you posted this at a good hour. do you always post this late",
                "i keep coming back to the bit in the middle. what is it",
                "saving this one. what made you pick it",
                "hope whoever is awake sees this. anyone else up",''',
    ),
    (
        '''                "THIS IS THE ONE. THIS IS THE ONE.",
                "PUT IT ON THE FRONT PAGE",
                "I HAVE WATCHED THIS ELEVEN TIMES",
                "EVERYONE LOOK AT THIS RIGHT NOW",
                "OK BUT MAKE ANOTHER ONE",''',
        '''                "THE COLOUR AT THE START. LOOK AT THE COLOUR AT THE START",
                "ELEVEN TIMES. ELEVEN. SOMEBODY STOP ME",
                "EVERYONE GET IN HERE AND LOOK AT THE MIDDLE BIT",
                "OK BUT MAKE ANOTHER ONE IMMEDIATELY I AM SERIOUS",
                "WHO FOUND THIS. WHO. I NEED TO KNOW",''',
    ),
]

for old, new in FALLBACKS:
    if old in s:
        s = s.replace(old, new, 1)
    else:
        print("  fallback anchor missing")

p.write_text(s, encoding="utf-8")
print("personas.py written")
