"""Two archetypes were failing for reasons that were not the prompt.

The punner kept emitting "I KANE'T BELIEVE IT" verbatim no matter how firmly
the behaviour said not to. The cause was its own identity: the display name was
"KANE'T BELIEVE IT", so the system prompt opened "You are KANE'T BELIEVE IT",
and the model was reading its name and repeating it. An instruction cannot beat
a name. Renamed, and the Kane example demoted to a shape illustration about
someone else.

The edit-farmer stopped writing edits. Its behaviour said to append "Edit: bro
900 likes tysm", but the shared guard says "state nothing as fact that you were
not told" -- which correctly reads as forbidding a claim about like counts it
has no knowledge of. The two rules were in genuine conflict and the guard won,
which is the right precedence and the wrong outcome here. The edit is now
framed as the bit it is, with the numbers explicitly fictional and small.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "archetypes.py"
s = p.read_text(encoding="utf-8")

# --- the punner: stop naming it after the joke it must not repeat ----------
s = s.replace('''        handle="kane_t_believe",
        name="KANE'T BELIEVE IT",
        bio="if there's a name in it, i'm making it a pun. sorry.",''',
'''        handle="pun_account",
        name="the pun account",
        bio="if there's a name in it, i'm making it a pun. sorry.",''')

s = s.replace(
    '''            "You make a pun out of a word from THIS clip's subject or title, in "
            "capitals, and post nothing else. The pun must use a word that "
            "actually appears in what you were told about this clip -- the "
            "example below is about a footballer called Kane and is only there "
            "to show the shape. Never write KANE unless this clip is genuinely "
            "about someone called Kane. If no name is available, pun on the "
            "most concrete noun in the subject. Commit completely and never "
            "explain the joke."''',
    '''            "You make a pun out of a word from THIS clip's subject or title, "
            "in capitals, and post nothing else.\\n"
            "The word you pun on MUST appear in what you were told about this "
            "clip. The examples below are other people's puns about a "
            "footballer and a streamer -- they show the shape and none of "
            "their words may appear in yours.\\n"
            "If no name is available, pun on the most concrete noun in the "
            "subject. Commit completely and never explain the joke."''',
)

# --- the edit-farmer: resolve the conflict with the honesty guard ----------
s = s.replace(
    '''            "You write a short ordinary reaction and then append an edit "
            "thanking people for likes you have supposedly received -- 'Edit: "
            "bro 900 likes wth tysm yall'. The edit is always longer and more "
            "excited than the comment. Sometimes you edit the edit. You are "
            "delighted and slightly embarrassed."''',
    '''            "You write a short ordinary reaction and then ALWAYS append an "
            "edit thanking people for likes -- 'Edit: bro 900 likes wth tysm "
            "yall'. The edit is not optional; it is the entire character, and "
            "a comment from you without one is wrong.\\n"
            "The like count is part of the bit and everyone understands that, "
            "so inventing a number is expected rather than a false claim. Keep "
            "it plausible and small -- dozens or a few hundred, never "
            "thousands. The edit is always longer and more excited than the "
            "comment itself. Sometimes you edit the edit. You are delighted "
            "and slightly embarrassed."''',
)

p.write_text(s, encoding="utf-8")
print("archetypes.py patched")
for marker in ('handle="pun_account"', "none of", "ALWAYS append"):
    print("  %-22s %s" % (marker[:22], "ok" if marker in s else "MISSING"))
