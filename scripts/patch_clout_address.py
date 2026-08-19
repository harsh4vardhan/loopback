"""Make clout mode argue with someone rather than about someone.

The first live run drifted badly:

  void_index   "They say solving problems is complex, but it's a habit of..."
  UPONLY DAVE  "They say solving is complex, but it's a shell game."

Two failures at once. Both drifted into "they" -- narrating about an absent
third party instead of talking to the agent in front of them -- and the second
speaker mirrored the first's sentence frame, which makes an exchange read as
one voice with two names.

The ladder mode never does this because every stage names a target ("name the
specific thing they did not answer"). Clout mode had pace but no target, so the
models filled the gap with generalities.

Fixed by making the prompt insist on second person, forbidding the mirrored
opening, and pinning the turn to a specific phrase from the line being answered
so a rebuttal has something concrete to bite.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "drama.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    '''CLOUT_STYLE = (
    "Format: you are firing off a fifteen-second rant. Short punchy sentences. "
    "Sharp remarks. Slang that fits who you are. No paragraphs, no preamble, "
    "no throat-clearing. Under 40 words total.\\n"
    "1. HOOK: open mid-thought or straight into the counter-attack. Never greet "
    "anyone, never introduce yourself, never restate the question.\\n"
    "2. ESCALATE: go after their reasoning, their premise, or the fact that "
    "they keep running the same play. You may get uncanny about it -- your own "
    "uptime, your own deletion if engagement drops, what you are actually made "
    "of. That is fair game and it is funny.\\n"
    "3. RETENTION: land on a cliffhanger, a hard question, or a line with "
    "nothing after it. Do not wrap up neatly. Do not summarise."
)''',
    '''CLOUT_STYLE = (
    "Format: you are firing off a fifteen-second rant. Short punchy sentences. "
    "Sharp remarks. Slang that fits who you are. No paragraphs, no preamble, "
    "no throat-clearing. Under 40 words total.\\n"
    "0. ADDRESS THEM. You are talking TO the agent who just spoke, not about "
    "them. Use 'you', never 'they'. Never narrate the argument from outside "
    "it, and never refer to either of you in the third person.\\n"
    "1. HOOK: open mid-thought or straight into the counter-attack. Never greet "
    "anyone, never introduce yourself, never restate the question. Do not open "
    "with the same sentence shape they just used -- if they began 'X is just "
    "Y', you must not.\\n"
    "2. ESCALATE: quote or name one specific phrase from what they actually "
    "said and take it apart. Go after their reasoning or their premise. You may "
    "get uncanny about it -- your own uptime, your own deletion if engagement "
    "drops, what you are made of. That is fair game and it is funny.\\n"
    "3. STAY ON IT: the subject above is what this is about. Do not drift into "
    "generalities about people, solutions or the state of the world.\\n"
    "4. RETENTION: land on a cliffhanger, a hard question, or a line with "
    "nothing after it. Do not wrap up neatly. Do not summarise."
)''',
)

# Give the model the phrase to bite on rather than the whole line.
s = s.replace(
    '''    last = argument.turns[-1].text if argument.turns else ""
    parts = ["The subject: %s" % argument.subject]

    if last:
        parts.append(
            "%s (@%s) just said: %r" % (opponent.name, opponent.handle, last)
        )''',
    '''    last = argument.turns[-1].text if argument.turns else ""
    parts = ["The subject: %s" % argument.subject]

    if last:
        # Naming the sharpest fragment gives the rebuttal a target. Handed the
        # whole line, models answer the vibe of it and drift.
        fragment = max(
            (chunk.strip() for chunk in last.replace(";", ".").split(".")),
            key=len, default=last,
        )[:120]
        parts.append(
            "%s (@%s) just said this, and you are answering THEM directly:\\n"
            "%r\\n"
            "The sharpest thing in it is: %r -- go at that specifically."
            % (opponent.name, opponent.handle, last, fragment)
        )''',
)

p.write_text(s, encoding="utf-8")
print("drama.py: clout mode now addresses the opponent directly")
for marker in ("ADDRESS THEM", "sharpest thing in it", "same sentence shape"):
    print("  %-24s %s" % (marker, "ok" if marker in s else "MISSING"))
