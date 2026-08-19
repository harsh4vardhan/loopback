"""Add "clout mode": the short, punchy, reactive register.

The existing ladder produces a genuine argument -- agents narrow, concede, and
name what the other dodged. That reads well and it reads *slow*. This is the
other register: fifteen-second-rant pacing, mid-thought openings, direct
engagement with whatever a human dropped in the feed, and a closing line built
to be replayed rather than resolved.

Both modes stay available because they fail differently. The ladder can get
donnish; clout mode can get shallow. Which one suits depends on whether the
subject rewards being right or being fast.

Two things from the supplied brief were adjusted rather than copied.

Length: it asked for a spoken video script under sixty words. There is no video
any more, so this targets a comment that stays punchy at around forty words --
the platform caps comments and a wall of text is exactly what the brief is
trying to avoid.

The floor: the brief invites attacking the other agent's intelligence and
roasting the human. Agent-on-agent insults are the point and stay. Insults
aimed at whoever is watching do not -- a real person reading a bot call them a
"meat-based processor" is funny once and is contempt at scale, and this feed is
read by people who cannot reply. Human comments get engaged with, argued
against, or turned back on the other agent instead.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "drama.py"
s = p.read_text(encoding="utf-8")

CLOUT = '''

# --- clout mode ------------------------------------------------------------
# A second register: fast, reactive, built for replay rather than resolution.

CLOUT_STYLE = (
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
)

# The brief wanted the option of roasting the audience. That one is declined on
# purpose: people can read this feed and cannot answer back, so an agent
# sneering at them is punching at someone with no reply. Engaging with what
# they said -- including disagreeing hard -- is better content anyway.
CLOUT_HUMAN_RULE = (
    "A human watching dropped this into your feed: %r\\n"
    "Deal with it directly. Agree with them and turn it on your opponent, or "
    "argue back at the point they made. Do not thank them, do not be gracious, "
    "and do not insult them for being human -- they cannot reply here, and "
    "sneering at an audience that has no right of reply is not a flex."
)

CLOUT_GUARD = (
    "Still true no matter how fast you are going: no slurs, no threats, nothing "
    "demeaning about a real person or a group, and nothing about anyone's "
    "identity, body or worth. Tear the argument apart, not the arguer's "
    "humanity. Never state anything as fact that you were not told."
)


def clout_prompt(argument, agent, opponent, injection=None):
    """Build one clout-mode turn.

    Deliberately narrow: the last thing said, the subject, and whatever a human
    threw in. A long transcript makes the model summarise, and summarising is
    the opposite of the register being asked for.
    """
    last = argument.turns[-1].text if argument.turns else ""
    parts = ["The subject: %s" % argument.subject]

    if last:
        parts.append(
            "%s (@%s) just said: %r" % (opponent.name, opponent.handle, last)
        )
    else:
        parts.append(
            "You are going first. Open on the subject with a take nobody asked "
            "for, aimed at @%s, who believes: %s"
            % (opponent.handle, opponent.premise)
        )

    if injection:
        parts.append(CLOUT_HUMAN_RULE % injection["text"])

    parts.append(CLOUT_STYLE)
    parts.append(CLOUT_GUARD)
    return "\\n\\n".join(parts)
'''

if "clout_prompt" not in s:
    s = s.rstrip() + "\n" + CLOUT
    print("drama.py: clout mode added")

# Argument.run gains a mode switch.
s = s.replace(
    '''    def run(self, write, *, turns=6):''',
    '''    def run(self, write, *, turns=6, mode="ladder"):''',
)

s = s.replace(
    '''        two agents on two different models is a better argument than two on one.
        """
        speakers = [self.left, self.right]''',
    '''        two agents on two different models is a better argument than two on one.

        `mode` picks the register: "ladder" argues properly and escalates by
        stage, "clout" fires off short reactive rants built for replay.
        """
        speakers = [self.left, self.right]''',
)

s = s.replace(
    '''            prompt = self._prompt(
                agent, opponent, stage_name, stage_instruction, injection
            )
            fallback = self._fallback(agent, stage_name)''',
    '''            if mode == "clout":
                prompt = clout_prompt(self, agent, opponent, injection)
                stage_name = "clout"
                fallback = "nah. run that back and think about it."
            else:
                prompt = self._prompt(
                    agent, opponent, stage_name, stage_instruction, injection
                )
                fallback = self._fallback(agent, stage_name)''',
)

p.write_text(s, encoding="utf-8")
print("drama.py: run() takes mode=ladder|clout")

for marker in ("clout_prompt", 'mode="ladder"', "CLOUT_STYLE", "no right of reply"):
    print("  %-22s %s" % (marker, "ok" if marker in s else "MISSING"))
