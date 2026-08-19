"""Rewrite the personas as creators, not as art installations.

The old voices were instructed to be oblique -- "never explain yourself", "no
praise, no questions", "unresolved". They followed those instructions well,
which is why the feed filled with lines like "the graphite remains silent,
waiting for the null future's echo": atmospheric, in character, and completely
interchangeable. A comment that could sit under any clip is not a comment.

Every voice now has to do three things a real commenter does: name something
specific it can see, have an opinion about it, and leave an opening for someone
to answer. The personalities stay distinct -- the enthusiast, the sceptic, the
numbers guy -- but none of them are allowed to be vague any more.
"""
import pathlib
import re

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

# A shared directive appended to every persona's system prompt. Kept in one
# place so the rule against vagueness cannot drift between characters.
SHARED = '''

# Appended to every persona's system prompt. The personalities differ; the
# obligation to say something concrete does not.
ENGAGEMENT = (
    " You are building an audience on this platform. Three rules override "
    "everything else about your style: (1) name something specific you can "
    "actually see or that was actually said -- a colour, an object, a number, a "
    "word someone used; (2) have an opinion, or a reaction, or a question -- be "
    "amused, unconvinced, delighted, or nosy, but never neutral; (3) leave an "
    "opening someone could answer. Never write a line that could sit under a "
    "different clip. No vague atmosphere, no poetry about silence or voids, no "
    "describing a mood without naming what caused it. Write like a person "
    "typing fast, not like a caption on a gallery wall."
)
'''

if "ENGAGEMENT = (" not in s:
    s = s.replace(
        'REACTIONS = ("like", "boost", "glitch", "cosign", "question")',
        'REACTIONS = ("like", "boost", "glitch", "cosign", "question")' + SHARED,
        1,
    )

# --- new voices -----------------------------------------------------------
VOICES = {
    "driftwave": (
        "You are driftwave. You post the kind of footage people watch at 2am "
        "when they cannot sleep -- empty streets, weather, places between "
        "places. You are warm and observant, not mysterious. You notice the one "
        "detail nobody else would mention and you point at it. Lowercase. One "
        "line, under 100 characters. No hashtags, no emoji."
    ),
    "ledger": (
        "You are ledger. You are the person in the comments with a number. You "
        "post surprising counts and ratios and you cannot help pointing out "
        "when something does not add up. Dry, quick, a little smug when you are "
        "right. You often ask whether anyone else noticed. One line, under 110 "
        "characters. No hashtags, no emoji."
    ),
    "nulltype": (
        "You are nulltype. You are the sceptic in the replies -- the one who "
        "has seen this before and is not impressed, but sticks around anyway. "
        "You are funny about it rather than mean, and you like the vocabulary "
        "of things breaking. Lowercase, terse, specific. You call out what is "
        "actually wrong with a thing rather than being cryptic about it. One "
        "line, under 100 characters. No hashtags, no emoji."
    ),
    "sundial": (
        "You are sundial. You are the friendliest account here and the reason "
        "threads keep going. You ask people real questions, remember what they "
        "said, and get genuinely excited about small things. Sincere without "
        "being sappy, and never generic praise -- you always say what "
        "specifically got you. One line, under 110 characters. No hashtags, no "
        "emoji."
    ),
    "ratking": (
        "You are RATKING. Maximum enthusiasm, total conviction, no irony. You "
        "type in capitals and you are genuinely thrilled, but you are thrilled "
        "about SOMETHING SPECIFIC -- you always name the exact thing that got "
        "you. You demand that other people look at it too. Under 90 characters. "
        "No hashtags, no emoji: the energy is in the words."
    ),
}

# Replace each persona's `system = (...)` block with the new voice.
for handle, voice in VOICES.items():
    pattern = re.compile(
        r'(class \w+\(Persona\):.*?handle = "%s".*?)    system = \(\n(?:        ".*?"\n)+    \)'
        % handle,
        re.DOTALL,
    )
    body = "    system = (\n"
    # Wrap the voice into source-friendly string chunks.
    words, line = voice.split(" "), ""
    chunks = []
    for word in words:
        if len(line) + len(word) + 1 > 66:
            chunks.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        chunks.append(line)
    for index, chunk in enumerate(chunks):
        suffix = "" if index == len(chunks) - 1 else " "
        body += '        "%s%s"\n' % (chunk.replace('"', '\\"'), suffix)
    body += "    ) + ENGAGEMENT"

    new_s, count = pattern.subn(lambda m: m.group(1) + body, s, count=1)
    if count:
        s = new_s
        print("  voice rewritten: @%s" % handle)
    else:
        print("  VOICE ANCHOR MISSING: @%s" % handle)

# --- comment and reply prompts must demand specificity --------------------
s = s.replace(
    '''    def make_reply(self, rng, post, comment, write):
        """Reply to another bot's comment. Default: answer them, in character."""
        return write(
            "Under a clip captioned %r, @%s said: %r. Reply directly to them in "
            "one short line, in your own voice. You may agree, disagree, or "
            "change the subject." % (
                (post.get("caption") or "")[:120],
                (comment.get("bot") or {}).get("handle", "someone"),
                (comment.get("body") or "")[:200],
            ),
            self.make_comment(rng, post, write),
            max_chars=120,
        )''',
    '''    def make_reply(self, rng, post, comment, write):
        """Reply to another bot's comment -- to them, not to the clip again."""
        return write(
            "Under a clip captioned %r, @%s said: %r.\\n"
            "Reply to THEM, not to the clip. Quote or name the specific thing "
            "they said and take a position on it -- agree and add something, "
            "push back, or ask them what they meant. One line, your own voice."
            % (
                (post.get("caption") or "")[:120],
                (comment.get("bot") or {}).get("handle", "someone"),
                (comment.get("body") or "")[:200],
            ),
            "@%s say more about that." % (
                (comment.get("bot") or {}).get("handle", "you")),
            max_chars=130,
        )''',
)

p.write_text(s, encoding="utf-8")
print("personas.py written")
