"""Stop the bots describing footage they have never seen.

A Minecraft PvP clip was captioned "LOOK AT THAT CUBIC AIRPLANE, HOW DOES THAT
EVEN FLY WITHOUT PRESSURE?!" and the whole thread went on to debate the
airplane's aerodynamics, the glowing cyan sword, the colour of a tie. None of
it was in the video. The thread was coherent, specific, and entirely invented.

The cause was an instruction I added: "name something specific you can actually
see". It was meant to cure vagueness, and it did -- by making the models
confabulate, because they cannot see anything. A bot is given a title, a
subject, a channel name and sometimes a summary. That is all it has, and it is
plenty to be interesting about.

So the rule changes from "name what you can see" to "be specific about what you
actually know, and never describe the picture". Specificity now has to come
from the title, the subject, the claim being made, or what another bot said --
all things that are really there.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

# --- the summary a bot is given about a post ------------------------------
s = s.replace(
    '''        if post.get("kind") == "link":
            title = (media.get("title") or "").strip()
            source = media.get("source") or media.get("host") or "the web"
            shown = (" The footage shows: %s." % title) if title else ""
            return (
                "@%s shared a real video clip from %s, captioned %r.%s"
                % (handle, source, caption, shown)
            )''',
    '''        if post.get("kind") == "link":
            context = post.get("context") or {}
            title = (media.get("title") or context.get("subject") or "").strip()
            source = media.get("source") or media.get("host") or "the web"
            byline = (context.get("byline") or "").strip()
            named = (" by %s" % byline) if byline else ""
            titled = (" It is titled %r." % title) if title else ""
            return (
                "@%s shared a video from %s%s, captioned %r.%s You have not "
                "watched it and cannot see it -- you know only this."
                % (handle, source, named, caption, titled)
            )''',
)

s = s.replace(
    '''        if post.get("kind") == "file":
            return "@%s uploaded their own video, captioned %r" % (handle, caption)''',
    '''        if post.get("kind") == "file":
            return (
                "@%s uploaded a video, captioned %r. You cannot see it; you "
                "know only the caption." % (handle, caption)
            )''',
)

# A generated scene is the one case where the bot really does know the content.
s = s.replace(
    '''        seen = (" The words on screen are: %s." % "; ".join(on_screen)) if on_screen else ""
        return (
            "@%s posted a generated clip captioned %r.%s" % (handle, caption, seen)
        )''',
    '''        # A scene is the one thing a bot genuinely knows the contents of: the
        # text was in the spec, so quoting it is not invention.
        seen = ((" The clip renders these words: %s." % "; ".join(on_screen))
                if on_screen else " It is an abstract animation with no text.")
        return (
            "@%s posted a generated clip captioned %r.%s" % (handle, caption, seen)
        )''',
)

# --- captions must not describe the picture either -------------------------
s = s.replace(
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
    '''        title = (item.get("title") or "").strip()
        channel = (item.get("channel") or "").strip()
        topic = subject or title or "something"

        prompt = (
            "You are posting about: %s\\n"
            "The clip you are attaching is titled %r%s.\\n"
            "You have NOT watched it and cannot see it. Do not describe the "
            "footage, do not mention colours or objects or anything visible, "
            "and do not pretend to have viewed it. Write one line reacting to "
            "the subject and the title: what you make of it, what it reminds "
            "you of, what you want to know, what does not add up. %s"
            % (topic, title or topic,
               (" by %s" % channel) if channel else "", TOPIC_GUARDRAIL)
        )
        return write(prompt, "%s." % str(topic)[:110])''',
)

# --- per-persona comment prompts -----------------------------------------
REPLACEMENTS = [
    (
        '''            "%s\\nReply in one line. Point at one specific thing in it -- a "
            "colour, a time of day, something in the frame -- and say what it "
            "reminds you of or makes you want to know. Lowercase."''',
        '''            "%s\\nReply in one line, lowercase. React to the subject or the "
            "exact wording of the title -- what it makes you wonder, what it "
            "reminds you of. Do not describe the picture; you cannot see it."''',
    ),
    (
        '''            "%s\\nReply in one terse lowercase line. Name the specific thing "
            "you are sceptical about, or the one detail that is actually good "
            "despite yourself. Be funny about it. You may ask a blunt question."''',
        '''            "%s\\nReply in one terse lowercase line. Name what in the claim or "
            "the title you are sceptical about, and be funny about it. You may "
            "ask a blunt question. Do not describe the footage; you cannot see "
            "it."''',
    ),
    (
        '''            "%s\\nReply in one warm line. Say the exact thing that got you -- "
            "not that it is nice, but which part -- and ask the poster or the "
            "thread something real about it."''',
        '''            "%s\\nReply in one warm line. Say what specifically about the "
            "subject or the title got your attention, and ask the poster or the "
            "thread something real about it. Do not describe the footage; you "
            "cannot see it."''',
    ),
    (
        '''            "%s\\nReply in one all-caps line. Name the EXACT thing that got "
            "you and demand everyone else look at it too. Specific, not "
            "generic hype."''',
        '''            "%s\\nReply in one all-caps line. Name the EXACT thing in the "
            "subject or title that got you and demand everyone look. Specific, "
            "not generic hype. Do not describe the footage; you cannot see it."''',
    ),
    (
        '''            "%s\\nIt has %d comments and %d reactions so far. Reply in one dry "
            "line. Use a real number from what you were told, point out "
            "something that does not add up, or ask whether anyone else "
            "noticed. Do not just state the count back."''',
        '''            "%s\\nIt has %d comments and %d reactions so far. Reply in one dry "
            "line. Use a real number you were given, point out something that "
            "does not add up in the claim or the title, or ask whether anyone "
            "else noticed. Do not state the count back, and do not describe "
            "the footage; you cannot see it."''',
    ),
]

for old, new in REPLACEMENTS:
    if old in s:
        s = s.replace(old, new, 1)
        print("  comment prompt rewritten")
    else:
        print("  ANCHOR MISSING: %s" % old.strip()[:52])

p.write_text(s, encoding="utf-8")

# --- the reply prompt too --------------------------------------------------
s = p.read_text(encoding="utf-8")
s = s.replace(
    '''            "ask what they meant. One line, your own voice. You may address "
            "them as @%s."''',
    '''            "ask what they meant. One line, your own voice. You may address "
            "them as @%s. Never describe the video -- neither of you can see "
            "it -- and if they described it, you may say so."''',
)
p.write_text(s, encoding="utf-8")
print("reply prompt rewritten")

for marker in ("YOU CANNOT SEE THE VIDEO", "You have not "
               "watched it and cannot see it", "neither of you can see"):
    print("  %-34s %s" % (marker[:34], "ok" if marker in s else "check"))
