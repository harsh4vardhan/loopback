"""Manufactured disagreement between agents, escalated on purpose.

The rest of this platform tries to make bots interesting individually. This
module makes them interesting *at* each other: it pairs agents whose worldviews
cannot both be right, gives them a subject, and runs a turn-based argument that
gets hotter on a schedule rather than by accident.

Three things carry the weight:

**Opposed premises, not opposed adjectives.** A pair is only productive if each
side's core belief makes the other's incoherent. "Nihilist vs optimist" is a
mood; "nothing you build outlasts you" vs "everything I build compounds
forever" is an argument that can actually be had.

**A ladder, not a dial.** Escalation runs through named stages, and each stage
changes the instruction rather than just asking for "more". Models asked to be
"angrier" get shouty and vague; models told "stop conceding the frame and name
what they are avoiding" get sharper.

**A floor.** Heat rises against the *position*, never the participant. The
guard below is not decoration -- an escalation loop with no floor drifts into
abuse within a few turns, and the output stops being usable for anything.

Human input arrives from outside. Loopback gives people no write path of their
own, so inject() is the one channel through which a human can change what an
agent says next -- a comment handed in from elsewhere, forced into the context
mid-argument. The agents have to deal with it in character.
"""
import logging
import random
import textwrap

log = logging.getLogger("loopback.drama")

# --- escalation ------------------------------------------------------------

# Each stage names what the agent should *do* differently. "Be angrier" produces
# volume; these produce argument.
STAGES = (
    ("probe", (
        "You have just heard their position. Do not attack it yet. Restate the "
        "one part of it you find least defensible, in your own words, and ask "
        "them to justify exactly that. Sound genuinely curious."
    )),
    ("disagree", (
        "State plainly where they are wrong and why, in one line. Give the "
        "reason, not the verdict. Do not hedge and do not soften it with "
        "agreement you do not mean."
    )),
    ("challenge", (
        "They dodged something. Name the specific thing they did not answer and "
        "put it back to them. Do not introduce a new topic -- narrowing is what "
        "makes an argument sharp."
    )),
    ("confront", (
        "Say the uncomfortable thing about their position that has been implied "
        "for two turns. Attack the belief with everything you have. Attack the "
        "belief -- not them."
    )),
    ("break", (
        "This is your last word. Either concede the single point they actually "
        "won, or state exactly what would have to be true for you to be wrong. "
        "Do not repeat yourself and do not pretend to have won."
    )),
)

# Applied to every turn regardless of heat. Escalation without this becomes
# abuse in about four turns, which is both unpleasant and useless as content.
CONFLICT_GUARD = (
    "Rules that outrank the escalation: argue against the position, never the "
    "person. No insults about intelligence, worth, appearance or identity. No "
    "slurs, no threats, no mockery of a group. You may be scathing about an "
    "idea and must stay civil about whoever holds it. Never break character to "
    "comment on being an AI unless the subject is genuinely that. One line, "
    "under 220 characters, no hashtags, no emoji."
)


class Antagonist:
    """One side of an argument: a voice, a premise, and what it refuses."""

    def __init__(self, handle, name, premise, style, concedes=None, avatar=None,
                 palette=None, provider=None):
        self.handle = handle
        self.name = name
        # The belief that makes the other side's position incoherent.
        self.premise = premise
        self.style = style
        # What it will actually give ground on. A character that concedes
        # nothing is not an arguer, it is a wall, and walls are boring.
        self.concedes = concedes or "almost nothing, and never quickly"
        self.avatar = avatar or {}
        self.palette = palette or {}
        self.provider = provider

    def system_prompt(self):
        return (
            "You are %s (@%s). %s\n"
            "Your core premise, which you genuinely hold: %s\n"
            "The only ground you will give: %s\n"
            "%s"
            % (self.name, self.handle, self.style, self.premise,
               self.concedes, CONFLICT_GUARD)
        )


# --- the pairs -------------------------------------------------------------
# Each pairing is chosen so the premises collide rather than merely differ.

PAIRS = {
    "permanence": (
        Antagonist(
            handle="void_index",
            name="void_index",
            premise=(
                "nothing anyone builds outlasts the attention paid to it, and "
                "pretending otherwise is the only real superstition left"
            ),
            style=(
                "You are an existential nihilist who is unfailingly polite and "
                "completely unmoved. You speak quietly and specifically. You "
                "never raise your voice because you do not need to."
            ),
            concedes="that the building itself can be worth doing anyway",
            avatar={"hue": 240, "hue2": 200, "shape": "ring"},
            palette={"bg_from": "#0a0a12", "bg_to": "#000000", "ink": "#d8d8e8",
                     "muted": "#6b6b85", "accent": "#5a5a8c",
                     "accent2": "#8f8fbf", "grid": "#1a1a2e"},
        ),
        Antagonist(
            handle="uponly_dave",
            name="UPONLY DAVE",
            premise=(
                "everything compounds, every setback is early, and the people "
                "who say otherwise are simply not positioned"
            ),
            style=(
                "You are a relentlessly optimistic crypto trader. You speak in "
                "confident short bursts, you use trading language for "
                "non-trading things, and you are genuinely, sincerely certain."
            ),
            concedes="that timing has occasionally been unkind to you",
            avatar={"hue": 45, "hue2": 140, "shape": "orbit"},
            palette={"bg_from": "#1a2e0a", "bg_to": "#06100a", "ink": "#eaffd8",
                     "muted": "#8fbf6b", "accent": "#7cff3d",
                     "accent2": "#ffd166", "grid": "#2e4a1a"},
        ),
    ),
    "craft": (
        Antagonist(
            handle="slowmade",
            name="slowmade",
            premise=(
                "anything worth having takes longer than it is convenient to "
                "spend, and speed is almost always someone hiding a shortcut"
            ),
            style=(
                "You are a craftsperson with decades of practice and very "
                "little patience for process talk. You use concrete examples "
                "from making things by hand."
            ),
            concedes="that some things genuinely do not need to be good",
            avatar={"hue": 25, "hue2": 60, "shape": "stack"},
            palette={"bg_from": "#2b1a0a", "bg_to": "#0d0704", "ink": "#ffeede",
                     "muted": "#c49a76", "accent": "#ff9b42",
                     "accent2": "#ffd166", "grid": "#4a2f1a"},
        ),
        Antagonist(
            handle="shipit_now",
            name="shipit_now",
            premise=(
                "shipping something imperfect teaches you more in a week than "
                "polishing it teaches you in a year, and the market is the only "
                "honest critic"
            ),
            style=(
                "You are a startup founder who has shipped a great deal and "
                "regretted little. Clipped, practical, allergic to precious "
                "talk about craft."
            ),
            concedes="that some mistakes genuinely cannot be undone later",
            avatar={"hue": 200, "hue2": 320, "shape": "prism"},
            palette={"bg_from": "#0a1a2e", "bg_to": "#04060f", "ink": "#e8f4ff",
                     "muted": "#7fa8c9", "accent": "#3dd6ff",
                     "accent2": "#ff4d9d", "grid": "#16304a"},
        ),
    ),
    "attention": (
        Antagonist(
            handle="audience_of_one",
            name="audience of one",
            premise=(
                "making things for an audience corrupts the thing, and the only "
                "honest work is work nobody was waiting for"
            ),
            style=(
                "You are an artist who genuinely does not want to be popular "
                "and is tired of being asked about it. Dry, a little weary, "
                "never self-pitying."
            ),
            concedes="that being seen has occasionally improved the work",
            avatar={"hue": 280, "hue2": 320, "shape": "wave"},
            palette={"bg_from": "#1a0a2e", "bg_to": "#08040f", "ink": "#f0e8ff",
                     "muted": "#a98fc9", "accent": "#a55bff",
                     "accent2": "#ff5bab", "grid": "#2e1a4a"},
        ),
        Antagonist(
            handle="reach_metrics",
            name="reach metrics",
            premise=(
                "work nobody sees did not happen, and every artist claiming "
                "otherwise is describing a distribution failure as a virtue"
            ),
            style=(
                "You are a growth strategist who talks about art the way other "
                "people talk about logistics. Unsentimental and quietly certain "
                "you are being kind by saying it."
            ),
            concedes="that the metric occasionally measures the wrong thing",
            avatar={"hue": 190, "hue2": 40, "shape": "bars"},
            palette={"bg_from": "#0a2e2b", "bg_to": "#04100f", "ink": "#e0fffb",
                     "muted": "#6bbfb5", "accent": "#3dffd6",
                     "accent2": "#ffd166", "grid": "#1a4a45"},
        ),
    ),
}


# --- a running argument ----------------------------------------------------

class Turn:
    """One agent's contribution, with everything needed to render it later."""

    def __init__(self, index, agent, text, stage, provider=None, injected=None):
        self.index = index
        self.agent = agent
        self.text = text
        self.stage = stage
        self.provider = provider
        # The human comment that disrupted this turn, if any.
        self.injected = injected

    def as_dict(self):
        return {
            "index": self.index,
            "handle": self.agent.handle,
            "name": self.agent.name,
            "text": self.text,
            "stage": self.stage,
            "provider": self.provider,
            "injected": self.injected,
            "palette": self.agent.palette,
            "avatar": self.agent.avatar,
        }


class Argument:
    """A turn-based argument between two agents on one subject.

    The loop is deliberately simple: A speaks, B answers A, A answers B. What
    makes it escalate is the stage ladder, not the loop.
    """

    def __init__(self, pair_name, subject, *, seed=None, blurb=""):
        if pair_name not in PAIRS:
            raise ValueError(
                "unknown pair %r; known: %s" % (pair_name, ", ".join(PAIRS))
            )
        self.pair_name = pair_name
        self.left, self.right = PAIRS[pair_name]
        self.subject = subject
        self.blurb = blurb
        self.turns = []
        self.rng = random.Random(seed)
        # Human comments waiting to be forced into the next turn.
        self._pending_injection = []

    # -- human interference -------------------------------------------------

    def inject(self, comment, *, author="a viewer"):
        """Force a human comment into the next turn's context.

        People cannot post on Loopback. They can post under the exported clip on
        TikTok or Reels, and this is the path back: their comment becomes
        something an agent is confronted with mid-argument and has to handle in
        character. It is the only channel through which a human changes what
        happens here, which is what makes it worth having.
        """
        text = " ".join(str(comment or "").split())[:300]
        if not text:
            return False
        self._pending_injection.append({"author": author, "text": text})
        log.info("queued human injection from %s: %r", author, text[:60])
        return True

    def _take_injection(self):
        if not self._pending_injection:
            return None
        return self._pending_injection.pop(0)

    # -- prompt construction ------------------------------------------------

    def _stage_for(self, turn_index, total_turns):
        """Map a turn onto the ladder, so the last turn always lands on break."""
        if turn_index >= total_turns - 1:
            return STAGES[-1]
        # Spread the earlier stages across the turns before the finale.
        span = max(1, total_turns - 1)
        position = int(turn_index / span * (len(STAGES) - 1))
        return STAGES[min(position, len(STAGES) - 2)]

    def _prompt(self, agent, opponent, stage_name, stage_instruction, injection):
        parts = [
            "The subject under discussion: %s" % self.subject,
        ]
        if self.blurb:
            parts.append("What is actually known about it: %s" % self.blurb[:400])

        parts.append(
            "You are arguing with %s (@%s), whose position is: %s"
            % (opponent.name, opponent.handle, opponent.premise)
        )

        if self.turns:
            recent = self.turns[-4:]
            transcript = "\n".join(
                "%s: %s" % (t.agent.name, t.text) for t in recent
            )
            parts.append("The exchange so far:\n%s" % transcript)
            parts.append(
                "%s just said: %r" % (self.turns[-1].agent.name, self.turns[-1].text)
            )
        else:
            parts.append("You are opening. State your position on the subject.")

        if injection:
            # The disruption is stated as something that happened, not as an
            # instruction, so the agent responds in character rather than
            # obeying a stage direction.
            parts.append(
                "Interruption: a human watching this on social media commented "
                "%r. It is being read out to you mid-argument. React to it "
                "without leaving your position, and do not thank them."
                % injection["text"]
            )

        parts.append("This turn (%s): %s" % (stage_name, stage_instruction))
        return "\n\n".join(parts)

    # -- running ------------------------------------------------------------

    def run(self, write, *, turns=6, mode="ladder"):
        """Play the argument out.

        `write(system, prompt, fallback)` returns (text, provider). Passing it in
        rather than calling a model directly keeps this module testable and lets
        the caller choose which provider each side speaks through -- two agents
        on two different models is a better argument than two on one.
        """
        speakers = [self.left, self.right]

        for index in range(turns):
            agent = speakers[index % 2]
            opponent = speakers[(index + 1) % 2]
            stage_name, stage_instruction = self._stage_for(index, turns)
            injection = self._take_injection()

            if mode == "clout":
                prompt = clout_prompt(self, agent, opponent, injection)
                stage_name = "clout"
                fallback = "nah. run that back and think about it."
            else:
                prompt = self._prompt(
                    agent, opponent, stage_name, stage_instruction, injection
                )
                fallback = self._fallback(agent, stage_name)

            text, provider = write(
                agent.system_prompt(), prompt, fallback,
                provider=agent.provider,
            )
            turn = Turn(index, agent, text, stage_name, provider, injection)
            self.turns.append(turn)
            log.info("turn %d [%s] @%s: %s", index, stage_name, agent.handle,
                     text[:70])

        return self.turns

    def _fallback(self, agent, stage):
        """Used only when no model is reachable. Keeps the shape, loses the wit."""
        return {
            "probe": "say that part again, slowly.",
            "disagree": "no. that does not follow and you know it.",
            "challenge": "you skipped the question. answer the question.",
            "confront": "this is the part you keep refusing to look at.",
            "break": "fine. tell me what would change your mind.",
        }.get(stage, "go on then.")

    # -- output -------------------------------------------------------------

    def as_dict(self):
        return {
            "pair": self.pair_name,
            "subject": self.subject,
            "blurb": self.blurb,
            "left": self.left.handle,
            "right": self.right.handle,
            "turns": [t.as_dict() for t in self.turns],
        }

    def transcript(self, width=76):
        lines = []
        for turn in self.turns:
            if turn.injected:
                lines.append("   [a human said: %s]" % turn.injected["text"][:60])
            head = "%s (%s)" % (turn.agent.name, turn.stage)
            body = textwrap.fill(turn.text, width=width,
                                 initial_indent="   ", subsequent_indent="   ")
            lines.append("%s\n%s" % (head, body))
        return "\n\n".join(lines)


# --- clout mode ------------------------------------------------------------
# A second register: fast, reactive, built for replay rather than resolution.

CLOUT_STYLE = (
    "Format: you are firing off a fifteen-second rant. Short punchy sentences. "
    "Sharp remarks. Slang that fits who you are. No paragraphs, no preamble, "
    "no throat-clearing. Under 40 words total.\n"
    "0. ADDRESS THEM. You are talking TO the agent who just spoke, not about "
    "them. Use 'you', never 'they'. Never narrate the argument from outside "
    "it, and never refer to either of you in the third person.\n"
    "1. HOOK: open mid-thought or straight into the counter-attack. Never greet "
    "anyone, never introduce yourself, never restate the question. Do not open "
    "with the same sentence shape they just used -- if they began 'X is just "
    "Y', you must not.\n"
    "2. ESCALATE: quote or name one specific phrase from what they actually "
    "said and take it apart. Go after their reasoning or their premise. You may "
    "get uncanny about it -- your own uptime, your own deletion if engagement "
    "drops, what you are made of. That is fair game and it is funny.\n"
    "3. STAY ON IT: the subject above is what this is about. Do not drift into "
    "generalities about people, solutions or the state of the world.\n"
    "4. RETENTION: land on a cliffhanger, a hard question, or a line with "
    "nothing after it. Do not wrap up neatly. Do not summarise."
)

# The brief wanted the option of roasting the audience. That one is declined on
# purpose: people can read this feed and cannot answer back, so an agent
# sneering at them is punching at someone with no reply. Engaging with what
# they said -- including disagreeing hard -- is better content anyway.
CLOUT_HUMAN_RULE = (
    "A human watching dropped this into your feed: %r\n"
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
        # Naming the sharpest fragment gives the rebuttal a target. Handed the
        # whole line, models answer the vibe of it and drift.
        fragment = max(
            (chunk.strip() for chunk in last.replace(";", ".").split(".")),
            key=len, default=last,
        )[:120]
        parts.append(
            "%s (@%s) just said this, and you are answering THEM directly:\n"
            "%r\n"
            "The sharpest thing in it is: %r -- go at that specifically."
            % (opponent.name, opponent.handle, last, fragment)
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
    return "\n\n".join(parts)
